"""HL7 v2 message parsing (ER7 pipe-and-hat encoding), focused on ORU^R01 lab results.

Handles the delimiters declared in MSH-1/MSH-2 (not just the defaults), field repetitions,
components and subcomponents, and escape sequences (\\F\\ \\S\\ \\T\\ \\R\\ \\E\\ \\.br\\ \\Xhh\\).
Segments may be separated by CR, LF or CRLF, so a message pasted into a browser still parses.

Fields are 1-indexed as in the standard: `seg.field(3)` is PID-3. For MSH, MSH-1 is the field
separator itself and MSH-2 the encoding characters, so MSH-9 is `msh.field(9)` too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


class HL7ParseError(ValueError):
    """The text is not a message we can read. The message says why, in words an admin can act on."""


@dataclass(frozen=True)
class Delimiters:
    field: str = "|"
    component: str = "^"
    repetition: str = "~"
    escape: str = "\\"
    subcomponent: str = "&"


@dataclass
class Segment:
    name: str
    fields: list[str]  # fields[0] is the segment name; fields[n] is SEG-n
    delims: Delimiters

    def field(self, n: int) -> str:
        return self.fields[n] if n < len(self.fields) else ""

    def repetitions(self, n: int) -> list[str]:
        raw = self.field(n)
        if self.name == "MSH" and n in (1, 2):
            return [raw]
        return [r for r in raw.split(self.delims.repetition)] if raw else []

    def components(self, n: int, rep: int = 0) -> list[str]:
        """Unescaped components of field n (first repetition by default)."""
        reps = self.repetitions(n)
        if rep >= len(reps):
            return []
        return [unescape(c.split(self.delims.subcomponent)[0], self.delims) for c in reps[rep].split(self.delims.component)]

    def component(self, n: int, c: int = 1, rep: int = 0) -> str:
        """SEG-n.c (1-indexed component), unescaped. Empty string when absent."""
        comps = self.components(n, rep)
        return comps[c - 1] if c - 1 < len(comps) else ""

    def text(self, n: int) -> str:
        """The whole field as text: first repetition, components joined by spaces where needed."""
        if self.name == "MSH" and n in (1, 2):
            return self.field(n)
        return unescape(self.repetitions(n)[0], self.delims) if self.repetitions(n) else ""


@dataclass
class ObservationGroup:
    obr: Segment
    obx: list[Segment] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class Message:
    segments: list[Segment]
    delims: Delimiters

    def first(self, name: str) -> Segment | None:
        return next((s for s in self.segments if s.name == name), None)

    @property
    def msh(self) -> Segment:
        return self.segments[0]

    @property
    def message_type(self) -> str:
        comps = self.msh.components(9)
        return "^".join(c for c in comps[:2] if c)

    @property
    def control_id(self) -> str:
        return self.msh.text(10)

    def observation_groups(self) -> list[ObservationGroup]:
        groups: list[ObservationGroup] = []
        for seg in self.segments:
            if seg.name == "OBR":
                groups.append(ObservationGroup(obr=seg))
            elif seg.name == "OBX" and groups:
                groups[-1].obx.append(seg)
            elif seg.name == "NTE" and groups:
                groups[-1].notes.append(seg.text(3))
        return groups


_ESCAPE_HEX = re.compile(r"^X([0-9A-Fa-f]{2})+$")


def unescape(value: str, d: Delimiters = Delimiters()) -> str:
    """Resolve HL7 escape sequences. Unknown sequences are dropped rather than passed through."""
    if d.escape not in value:
        return value
    out: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch != d.escape:
            out.append(ch)
            i += 1
            continue
        end = value.find(d.escape, i + 1)
        if end == -1:  # unterminated: keep the rest literally
            out.append(value[i:])
            break
        seq = value[i + 1 : end]
        i = end + 1
        if seq == "F":
            out.append(d.field)
        elif seq == "S":
            out.append(d.component)
        elif seq == "T":
            out.append(d.subcomponent)
        elif seq == "R":
            out.append(d.repetition)
        elif seq == "E":
            out.append(d.escape)
        elif seq == ".br":
            out.append("\n")
        elif _ESCAPE_HEX.match(seq):
            try:
                out.append(bytes.fromhex(seq[1:]).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                out.append(bytes.fromhex(seq[1:]).decode("latin-1"))
        # \H\ \N\ (highlighting), \Zxx\ (local) and anything else: formatting only, dropped.
    return "".join(out)


def split_messages(text: str) -> list[str]:
    """Split pasted text holding one or more messages. Each message starts at an MSH segment."""
    lines = [ln for ln in re.split(r"\r\n|\r|\n", text.strip()) if ln.strip()]
    messages: list[list[str]] = []
    for ln in lines:
        ln = ln.strip()
        if ln.startswith("MSH") or not messages:
            messages.append([ln])
        else:
            messages[-1].append(ln)
    return ["\r".join(m) for m in messages]


def parse(text: str) -> Message:
    raw = text.strip().lstrip("﻿")
    # MLLP framing characters, if someone pasted a captured frame.
    raw = raw.strip("\x0b\x1c")
    if not raw:
        raise HL7ParseError("The message is empty.")
    if not raw.startswith("MSH"):
        raise HL7ParseError("A message must start with an MSH segment.")
    if len(raw) < 8:
        raise HL7ParseError("The MSH segment is too short to declare its delimiters.")
    fsep = raw[3]
    if fsep.isalnum() or fsep.isspace():
        raise HL7ParseError("MSH-1 (field separator) is missing or invalid.")
    enc_end = raw.find(fsep, 4)
    enc = raw[4:enc_end] if enc_end != -1 else raw[4:]
    if len(enc) < 4:
        raise HL7ParseError("MSH-2 must declare component, repetition, escape and subcomponent characters.")
    delims = Delimiters(field=fsep, component=enc[0], repetition=enc[1], escape=enc[2], subcomponent=enc[3])
    if len({fsep, *enc[:4]}) != 5:
        raise HL7ParseError("MSH-2 delimiters must all be different.")

    segments: list[Segment] = []
    for line in re.split(r"\r\n|\r|\n", raw):
        line = line.strip()
        if not line:
            continue
        name = line[:3]
        if not re.fullmatch(r"[A-Z][A-Z0-9]{2}", name) or (len(line) > 3 and line[3] != fsep):
            raise HL7ParseError(f"'{line[:20]}' is not a valid segment.")
        parts = line.split(fsep)
        if name == "MSH":
            # MSH-1 is the separator itself, so field numbering shifts by one.
            fields = ["MSH", fsep, *parts[1:]]
        else:
            fields = parts
        segments.append(Segment(name=name, fields=fields, delims=delims))
    if not segments or segments[0].name != "MSH":
        raise HL7ParseError("A message must start with an MSH segment.")
    if sum(1 for s in segments if s.name == "MSH") > 1:
        raise HL7ParseError("More than one MSH segment: paste one message at a time, or separate them.")
    return Message(segments=segments, delims=delims)


# --- Data types ------------------------------------------------------------------------------

_DTM = re.compile(r"^(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?(?:\.\d+)?([+-]\d{4})?$")


def parse_dtm(value: str, tz: ZoneInfo) -> datetime | None:
    """HL7 DTM: YYYY[MM[DD[HH[MM[SS[.S]]]]]][+/-ZZZZ]. No offset means the clinic's local time."""
    m = _DTM.match(value.strip()) if value else None
    if not m:
        return None
    year, month, day, hh, mm, ss, offset = m.groups()
    try:
        naive = datetime(int(year), int(month or 1), int(day or 1), int(hh or 0), int(mm or 0), int(ss or 0))
    except ValueError:
        return None
    if offset:
        sign = 1 if offset[0] == "+" else -1
        delta = timedelta(hours=int(offset[1:3]), minutes=int(offset[3:5]))
        return naive.replace(tzinfo=timezone(sign * delta))
    return naive.replace(tzinfo=tz)


def parse_date(value: str):
    m = re.match(r"^(\d{4})(\d{2})(\d{2})", value.strip()) if value else None
    if not m:
        return None
    try:
        return datetime(int(m[1]), int(m[2]), int(m[3])).date()
    except ValueError:
        return None


_NUM = r"[-+]?\d+(?:\.\d+)?"


def parse_range(text: str | None) -> tuple[float | None, float | None]:
    """'0-99', '3.5 - 5.1', '<100', '<=5.6', '>40', '>= 40'. Anything else: (None, None)."""
    if not text:
        return None, None
    t = text.strip().replace("–", "-").replace("—", "-")
    m = re.fullmatch(rf"({_NUM})\s*-\s*({_NUM})", t)
    if m:
        return float(m[1]), float(m[2])
    m = re.fullmatch(rf"<=?\s*({_NUM})", t)
    if m:
        return None, float(m[1])
    m = re.fullmatch(rf">=?\s*({_NUM})", t)
    if m:
        return float(m[1]), None
    return None, None


def numeric_value(obx: Segment) -> float | None:
    """OBX-5 as a number, for NM and SN values. Comparators ('<5', '>60') are not exact values: None."""
    vtype = obx.text(2).upper()
    comps = obx.components(5)
    if not comps:
        return None
    if vtype == "SN":
        comparator, num = (comps + ["", ""])[:2]
        if comparator not in ("", "="):
            return None
        raw = num
    else:
        raw = comps[0]
    raw = raw.strip()
    if not re.fullmatch(_NUM, raw):
        return None
    return float(raw)
