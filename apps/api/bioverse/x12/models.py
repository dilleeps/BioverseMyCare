"""Typed models the X12 builders take and the parsers return. Money is integer cents throughout."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

Gender = Literal["F", "M", "U"]
Relationship = Literal["self", "spouse", "child", "other"]

# X12 individual relationship codes (SBR02 / INS02 / PAT01).
RELATIONSHIP_CODES = {"self": "18", "spouse": "01", "child": "19", "other": "G8"}
RELATIONSHIP_FROM_CODE = {v: k for k, v in RELATIONSHIP_CODES.items()}


class Person(BaseModel):
    first_name: str = ""
    last_name: str = ""
    birth_date: date | None = None
    gender: Gender = "U"


class Address(BaseModel):
    line1: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""

    def complete(self) -> bool:
        return bool(self.line1 and self.city and self.state and self.zip)


class Subscriber(Person):
    member_id: str = ""
    group_number: str | None = None
    address: Address | None = None


class Payer(BaseModel):
    name: str
    payer_id: str
    phone: str | None = None


class Provider(BaseModel):
    """An organization (billing provider, information receiver) or a person (rendering provider)."""

    name: str = ""                 # organization name, or last name for a person
    first_name: str | None = None
    npi: str = ""
    tax_id: str | None = None
    taxonomy: str | None = None
    address: Address | None = None


# --- 270 / 271 ------------------------------------------------------------------------------------


class EligibilityInquiry(BaseModel):
    payer: Payer
    provider: Provider
    subscriber: Subscriber
    patient: Person | None = None           # set when the patient is a dependent, not the subscriber
    relationship: Relationship = "self"
    service_types: list[str] = Field(default_factory=lambda: ["30"])
    date_of_service: date
    trace_number: str
    reference: str                          # BHT03


class Accumulator(BaseModel):
    """A deductible or out-of-pocket maximum: the yearly total and what is left of it."""

    total_cents: int | None = None
    remaining_cents: int | None = None

    @property
    def met_cents(self) -> int | None:
        if self.total_cents is None or self.remaining_cents is None:
            return None
        return max(0, self.total_cents - self.remaining_cents)


class Copay(BaseModel):
    service_type: str
    label: str
    amount_cents: int
    in_network: bool | None = True
    note: str | None = None


class Coinsurance(BaseModel):
    service_type: str
    label: str
    percent: int
    in_network: bool | None = True


class Rejection(BaseModel):
    code: str
    reason: str
    follow_up: str | None = None


class EligibilityResult(BaseModel):
    status: Literal["active", "inactive", "not_found", "error"]
    payer: Payer | None = None
    member_id: str | None = None
    subscriber: Person | None = None
    group_number: str | None = None
    plan_name: str | None = None
    plan_begin: date | None = None
    plan_end: date | None = None
    deductible_individual: Accumulator = Field(default_factory=Accumulator)
    deductible_family: Accumulator = Field(default_factory=Accumulator)
    oop_individual: Accumulator = Field(default_factory=Accumulator)
    oop_family: Accumulator = Field(default_factory=Accumulator)
    copays: list[Copay] = Field(default_factory=list)
    coinsurance: list[Coinsurance] = Field(default_factory=list)
    rejections: list[Rejection] = Field(default_factory=list)
    messages: list[str] = Field(default_factory=list)
    trace_number: str | None = None


# --- 837P ----------------------------------------------------------------------------------------


class ServiceLine(BaseModel):
    procedure_code: str
    modifiers: list[str] = Field(default_factory=list)
    charge_cents: int
    units: int = 1
    service_date: date
    diagnosis_pointers: list[int] = Field(default_factory=lambda: [1])
    place_of_service: str | None = None
    description: str | None = None


class ProfessionalClaim(BaseModel):
    patient_control_number: str
    submitter: Provider
    submitter_contact: str = "BILLING OFFICE"
    submitter_phone: str = ""
    receiver: Provider
    billing_provider: Provider
    payer: Payer
    subscriber: Subscriber
    relationship: Relationship = "self"
    patient: Person | None = None           # when the patient is not the subscriber
    patient_address: Address | None = None
    claim_filing_indicator: str = "CI"      # CI = commercial insurance
    place_of_service: str = "11"            # 11 = office
    frequency_code: str = "1"               # 1 = original claim
    diagnosis_codes: list[str] = Field(default_factory=list)
    prior_authorization: str | None = None
    rendering_provider: Provider | None = None
    service_lines: list[ServiceLine] = Field(default_factory=list)
    reference: str = ""                     # BHT03 batch reference

    @property
    def total_charge_cents(self) -> int:
        return sum(line.charge_cents for line in self.service_lines)


# --- 277CA --------------------------------------------------------------------------------------


class ClaimAcknowledgment(BaseModel):
    patient_control_number: str
    category_code: str
    status_code: str
    entity_code: str | None = None
    accepted: bool
    message: str
    payer_claim_number: str | None = None
    charge_cents: int = 0
    service_date: date | None = None
    patient: Person | None = None
    member_id: str | None = None


class Acknowledgment277(BaseModel):
    payer: Payer
    receiver_name: str = ""
    receiver_id: str = ""
    billing_provider: Provider | None = None
    batch_reference: str = ""
    received_on: date | None = None
    claims: list[ClaimAcknowledgment] = Field(default_factory=list)


# --- 835 ----------------------------------------------------------------------------------------


class Adjustment(BaseModel):
    group: str
    reason_code: str
    amount_cents: int
    quantity: str | None = None


class RemitServiceLine(BaseModel):
    procedure_code: str
    modifiers: list[str] = Field(default_factory=list)
    charge_cents: int
    paid_cents: int
    units: int = 1
    service_date: date | None = None
    allowed_cents: int | None = None
    adjustments: list[Adjustment] = Field(default_factory=list)


class RemitClaim(BaseModel):
    patient_control_number: str
    status_code: str
    charge_cents: int
    paid_cents: int
    patient_resp_cents: int = 0
    filing_indicator: str = "CI"
    payer_claim_number: str = ""
    patient: Person | None = None
    member_id: str | None = None
    service_date: date | None = None
    adjustments: list[Adjustment] = Field(default_factory=list)       # claim-level CAS
    service_lines: list[RemitServiceLine] = Field(default_factory=list)

    def all_adjustments(self) -> list[Adjustment]:
        return self.adjustments + [a for line in self.service_lines for a in line.adjustments]

    def patient_resp_by_reason(self, code: str) -> int:
        return sum(a.amount_cents for a in self.all_adjustments() if a.group == "PR" and a.reason_code == code)


class ProviderAdjustment(BaseModel):
    provider_id: str
    fiscal_date: date
    reason_code: str
    reference: str | None = None
    amount_cents: int               # positive reduces the payment; negative (e.g. interest) increases it


class Remittance(BaseModel):
    payer: Payer
    payee: Provider
    payment_cents: int
    credit_debit: str = "C"
    payment_method: str = "ACH"      # ACH, CHK, NON
    payment_date: date
    trace_number: str
    claims: list[RemitClaim] = Field(default_factory=list)
    provider_adjustments: list[ProviderAdjustment] = Field(default_factory=list)
