"""X12 5010 envelope: ISA/GS/ST ... SE/GE/IEA, delimiters, control numbers and segment counts.

Building: `build_interchange(env, functional_id, version, transaction_set, bodies)` wraps one or more
transaction-set bodies (segments between ST and SE) in a complete interchange with correct counts.

Parsing: `parse_interchange(text)` reads the delimiters from the fixed-width ISA segment, splits the
interchange, and checks every envelope rule (matching control numbers, SE01 segment counts, GE01 and
IEA01 counts). Problems come back as one `X12Error` listing readable messages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

Segment = list[str]


class X12Error(ValueError):
    """One or more readable problems with an X12 document or with the data needed to build one."""

    def __init__(self, errors: list[str] | str):
        self.errors = [errors] if isinstance(errors, str) else list(errors)
        super().__init__("; ".join(self.errors))


@dataclass(frozen=True)
class Delimiters:
    element: str = "*"
    sub: str = ":"
    repetition: str = "^"
    segment: str = "~"

    def all(self) -> str:
        return self.element + self.sub + self.repetition + self.segment


DEFAULT = Delimiters()

# Functional identifier (GS01) for each transaction set we exchange.
FUNCTIONAL_IDS = {"270": "HS", "271": "HB", "837": "HC", "277": "HN", "835": "HP", "999": "FA"}


@dataclass
class Envelope:
    """Who is sending to whom, and the control numbers for this interchange."""

    sender_id: str
    receiver_id: str
    control_number: int                     # ISA13, 1..999999999
    group_control_number: int | None = None  # GS06; defaults to the ISA control number
    sender_qualifier: str = "ZZ"
    receiver_qualifier: str = "ZZ"
    gs_sender: str | None = None
    gs_receiver: str | None = None
    usage: str = "T"                        # T = test, P = production
    ack_requested: str = "0"
    timestamp: datetime = field(default_factory=datetime.now)


# --- Values --------------------------------------------------------------------------------------


_UNSAFE = re.compile(r"[*:^~\r\n]")


def clean(value: object, d: Delimiters = DEFAULT) -> str:
    """An element value with delimiter characters removed. None becomes empty."""
    if value is None:
        return ""
    text = str(value)
    for ch in d.all():
        text = text.replace(ch, " ")
    return _UNSAFE.sub(" ", text).strip()


def name_value(value: object) -> str:
    return clean(value).upper()


def amount(cents: int) -> str:
    """Integer cents as an X12 R (decimal) value: 38000 -> '380', 21050 -> '210.5', -125 -> '-1.25'."""
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(int(cents)), 100)
    if frac == 0:
        return f"{sign}{whole}"
    return f"{sign}{whole}.{frac:02d}".rstrip("0")


def cents(value: str | None, *, what: str = "amount") -> int:
    """An X12 decimal as integer cents. Raises X12Error on anything that is not a number."""
    if value is None or value == "":
        return 0
    try:
        return int((Decimal(value) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        raise X12Error(f"{what} '{value}' is not a number") from None


def percent_value(pct: int) -> str:
    """20 -> '.2' (EB08 carries percentages as a decimal fraction)."""
    text = f"{Decimal(pct) / Decimal(100):f}"
    text = text.rstrip("0").rstrip(".") if "." in text else text
    return text[1:] if text.startswith("0.") else text


def percent_from(value: str) -> int:
    try:
        return int((Decimal(value) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        raise X12Error(f"percentage '{value}' is not a number") from None


def d8(day: date) -> str:
    return day.strftime("%Y%m%d")


def parse_d8(value: str, *, what: str = "date") -> date:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except (TypeError, ValueError):
        raise X12Error(f"{what} '{value}' is not a CCYYMMDD date") from None


def parse_date_value(qualifier: str, value: str, *, what: str = "date") -> tuple[date, date | None]:
    """DTP/DTM value with D8 (one date) or RD8 (CCYYMMDD-CCYYMMDD range)."""
    if qualifier == "RD8":
        start, _, end = value.partition("-")
        return parse_d8(start, what=what), parse_d8(end, what=what) if end else None
    return parse_d8(value, what=what), None


def seg(*elements: object) -> Segment:
    """A segment from its id and elements. Trailing empty elements are dropped, as X12 requires."""
    out = [str(elements[0])] + [e if isinstance(e, str) else ("" if e is None else str(e)) for e in elements[1:]]
    while len(out) > 1 and out[-1] == "":
        out.pop()
    return out


def el(segment: Segment, index: int) -> str:
    """Element `index` (1-based, as the implementation guides number them), or '' when absent."""
    return segment[index] if index < len(segment) else ""


def render_segment(segment: Segment, d: Delimiters = DEFAULT) -> str:
    return d.element.join(segment) + d.segment


def render(segments: list[Segment], d: Delimiters = DEFAULT) -> str:
    """Segments as text, one per line for readability (the newline after the terminator is ignored)."""
    return "\n".join(render_segment(s, d) for s in segments) + "\n"


# --- Building ------------------------------------------------------------------------------------


def _fixed(value: str, width: int) -> str:
    value = clean(value)
    if len(value) > width:
        raise X12Error(f"'{value}' is longer than {width} characters")
    return value.ljust(width)


def _control(n: int, width: int = 9) -> str:
    if not 1 <= n < 10**width:
        raise X12Error(f"control number {n} is out of range")
    return f"{n:0{width}d}"


def isa_segment(env: Envelope, d: Delimiters = DEFAULT) -> Segment:
    ts = env.timestamp
    return [
        "ISA", "00", " " * 10, "00", " " * 10,
        _fixed(env.sender_qualifier, 2), _fixed(env.sender_id, 15),
        _fixed(env.receiver_qualifier, 2), _fixed(env.receiver_id, 15),
        ts.strftime("%y%m%d"), ts.strftime("%H%M"), d.repetition, "00501",
        _control(env.control_number), env.ack_requested, env.usage, d.sub,
    ]


def build_interchange(
    env: Envelope,
    *,
    transaction_set: str,
    version: str,
    bodies: list[list[Segment]],
    first_st_control: int = 1,
    d: Delimiters = DEFAULT,
) -> str:
    """A complete interchange: one functional group holding one transaction set per body."""
    if not bodies:
        raise X12Error("An interchange needs at least one transaction set")
    gid = FUNCTIONAL_IDS[transaction_set]
    group_control = env.group_control_number or env.control_number
    ts = env.timestamp
    segments: list[Segment] = [
        isa_segment(env, d),
        ["GS", gid, clean(env.gs_sender or env.sender_id), clean(env.gs_receiver or env.receiver_id),
         ts.strftime("%Y%m%d"), ts.strftime("%H%M"), str(group_control), "X", version],
    ]
    for i, body in enumerate(bodies):
        control = f"{first_st_control + i:04d}"
        st = ["ST", transaction_set, control, version]
        # SE01 counts every segment from ST to SE inclusive.
        segments += [st, *body, ["SE", str(len(body) + 2), control]]
    segments += [["GE", str(len(bodies)), str(group_control)], ["IEA", "1", _control(env.control_number)]]
    return render(segments, d)


# --- Parsing -------------------------------------------------------------------------------------


@dataclass
class Transaction:
    set_id: str
    control: str
    version: str
    segments: list[Segment]         # from ST through SE inclusive

    @property
    def body(self) -> list[Segment]:
        return self.segments[1:-1]


@dataclass
class Group:
    functional_id: str
    sender: str
    receiver: str
    control: str
    version: str
    transactions: list[Transaction]


@dataclass
class Interchange:
    sender_id: str
    receiver_id: str
    control: str
    usage: str
    timestamp: datetime | None
    delimiters: Delimiters
    groups: list[Group]

    def transactions(self, set_id: str | None = None) -> list[Transaction]:
        return [t for g in self.groups for t in g.transactions if set_id is None or t.set_id == set_id]


def detect_delimiters(text: str) -> Delimiters:
    if not text.startswith("ISA"):
        raise X12Error("This is not an X12 interchange: it must start with an ISA segment")
    if len(text) < 106:
        raise X12Error("The ISA segment is incomplete: it must be 106 characters long")
    element = text[3]
    isa = text[:106]
    if isa.count(element) != 16:
        raise X12Error("The ISA segment must have exactly 16 elements")
    return Delimiters(element=element, repetition=isa[82], sub=isa[104], segment=isa[105])


def split_segments(text: str) -> tuple[list[Segment], Delimiters]:
    text = text.lstrip("﻿ \r\n\t")
    d = detect_delimiters(text)
    raw = [s.strip("\r\n\t ") for s in text.split(d.segment)]
    return [s.split(d.element) for s in raw if s], d


def parse_interchange(text: str) -> Interchange:
    segments, d = split_segments(text)
    errors: list[str] = []
    isa = segments[0]
    ts = None
    try:
        ts = datetime.strptime(isa[9] + isa[10], "%y%m%d%H%M")
    except ValueError:
        errors.append(f"ISA09/ISA10 date and time '{isa[9]} {isa[10]}' are not valid")
    if isa[12] != "00501":
        errors.append(f"ISA12 version is '{isa[12]}'; only 00501 (5010) is supported")
    if not re.fullmatch(r"\d{9}", isa[13]):
        errors.append(f"ISA13 control number '{isa[13]}' must be 9 digits")

    groups: list[Group] = []
    group: Group | None = None
    txn: Transaction | None = None
    iea: Segment | None = None
    envelope_ids = ("ST", "GS", "GE", "IEA", "ISA")
    for s in segments[1:]:
        sid = s[0]
        if txn is not None and sid not in envelope_ids:
            txn.segments.append(s)
            if sid == "SE":
                expected = len(txn.segments)
                if el(s, 1) != str(expected):
                    errors.append(f"SE01 in transaction {txn.control} says {el(s, 1) or 'nothing'} segments; "
                                  f"it has {expected}")
                if el(s, 2) != txn.control:
                    errors.append(f"SE02 control number '{el(s, 2)}' does not match ST02 '{txn.control}'")
                txn = None
            continue
        if txn is not None:
            errors.append(f"Transaction {txn.control} is missing its SE segment")
            txn = None
        if sid == "GS":
            if group is not None:
                errors.append(f"Functional group {group.control} is missing its GE segment")
            group = Group(el(s, 1), el(s, 2), el(s, 3), el(s, 6), el(s, 8), [])
            groups.append(group)
        elif sid == "ST":
            if group is None:
                errors.append("ST segment found outside a functional group (no GS)")
                group = Group("", "", "", "", "", [])
                groups.append(group)
            txn = Transaction(el(s, 1), el(s, 2), el(s, 3) or group.version, [s])
            group.transactions.append(txn)
        elif sid == "GE":
            if group is None:
                errors.append("GE segment without a matching GS")
                continue
            if el(s, 1) != str(len(group.transactions)):
                errors.append(f"GE01 says {el(s, 1)} transaction sets; group {group.control} has "
                              f"{len(group.transactions)}")
            if el(s, 2) != group.control:
                errors.append(f"GE02 control number '{el(s, 2)}' does not match GS06 '{group.control}'")
            group = None
        elif sid == "IEA":
            iea = s
        else:
            errors.append(f"Segment {sid} is outside any transaction set")
    if txn is not None:
        errors.append(f"Transaction {txn.control} is missing its SE segment")
    if group is not None:
        errors.append(f"Functional group {group.control} is missing its GE segment")
    if iea is None:
        errors.append("The interchange is missing its IEA segment")
    else:
        if el(iea, 1) != str(len(groups)):
            errors.append(f"IEA01 says {el(iea, 1)} functional groups; the interchange has {len(groups)}")
        if el(iea, 2) != isa[13]:
            errors.append(f"IEA02 control number '{el(iea, 2)}' does not match ISA13 '{isa[13]}'")
    if errors:
        raise X12Error(errors)
    return Interchange(
        sender_id=isa[6].strip(), receiver_id=isa[8].strip(), control=isa[13], usage=isa[15],
        timestamp=ts, delimiters=d, groups=groups,
    )


def single_transaction(text: str, set_id: str) -> tuple[Interchange, Transaction]:
    ic = parse_interchange(text)
    found = ic.transactions(set_id)
    if not found:
        kinds = ", ".join(sorted({t.set_id for t in ic.transactions()})) or "none"
        raise X12Error(f"Expected a {set_id} transaction set; found {kinds}")
    return ic, found[0]


def composite(value: str, d: Delimiters) -> list[str]:
    return value.split(d.sub) if value else []


def repeats(value: str, d: Delimiters) -> list[str]:
    return [v for v in value.split(d.repetition)] if value else []
