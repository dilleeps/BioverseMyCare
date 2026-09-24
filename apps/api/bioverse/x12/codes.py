"""Code lists used by the X12 builders and parsers, with plain-language labels.

These are small, curated subsets of the published lists (X12 external code sources 507 and 508 for
claim status, 139 for CARCs). A production system loads the full lists; unknown codes still parse and
show their raw code.
"""

from __future__ import annotations

import re

# Eligibility service type codes (EB03 / EQ01).
SERVICE_TYPES = {
    "1": "Medical care",
    "30": "Health benefit plan coverage",
    "33": "Chiropractic",
    "35": "Dental care",
    "47": "Hospital",
    "48": "Hospital inpatient",
    "50": "Hospital outpatient",
    "86": "Emergency services",
    "88": "Pharmacy",
    "98": "Office visit",
    "A4": "Psychiatric",
    "AL": "Vision (optometry)",
    "MH": "Mental health",
    "UC": "Urgent care",
}

# EB01 eligibility or benefit information codes.
BENEFIT_CODES = {
    "1": "Active coverage",
    "6": "Inactive",
    "7": "Inactive, pending eligibility update",
    "8": "Inactive, pending investigation",
    "A": "Coinsurance",
    "B": "Co-payment",
    "C": "Deductible",
    "G": "Out of pocket (stop loss)",
}

# EB06 time period qualifiers we read.
TIME_TOTAL = {"21", "22", "23", "25", "26"}   # years, service year, calendar year, contract, episode
TIME_REMAINING = "29"
TIME_YEAR_TO_DATE = "24"
TIME_VISIT = "27"

# AAA request validation reject reasons (271).
AAA_REASONS = {
    "15": "Required application data missing",
    "41": "Authorization or access restrictions",
    "42": "The payer's system is unable to respond right now",
    "43": "Invalid or missing provider identification",
    "57": "Invalid or missing date of service",
    "58": "Invalid or missing date of birth",
    "72": "Invalid or missing member ID",
    "73": "Invalid or missing subscriber name",
    "75": "Subscriber or insured not found",
    "76": "Duplicate subscriber or insured ID",
}

# 277CA claim status category codes (STC01-1, code source 507).
STATUS_CATEGORIES = {
    "A0": "Acknowledgement: forwarded to another entity",
    "A1": "Acknowledgement: received",
    "A2": "Accepted into adjudication",
    "A3": "Returned as unprocessable",
    "A4": "Not found",
    "A6": "Rejected for missing information",
    "A7": "Rejected for invalid information",
    "A8": "Rejected for a relational field in error",
}
ACCEPTED_CATEGORIES = {"A1", "A2"}

# Claim status codes (STC01-2, code source 508), common ones.
STATUS_CODES = {
    "19": "Entity acknowledges receipt of the claim",
    "20": "Accepted for processing",
    "21": "Missing or invalid information",
    "33": "Subscriber and subscriber ID not found",
    "116": "Claim submitted to the incorrect payer",
    "145": "Entity's primary identifier",
    "187": "Date(s) of service",
    "247": "Line information",
    "254": "Principal diagnosis code",
    "562": "Entity's National Provider Identifier (NPI)",
}

# Entity identifier codes used in STC01-3 and NM1.
ENTITIES = {"85": "billing provider", "82": "rendering provider", "IL": "subscriber", "QC": "patient", "PR": "payer"}

# CLP02 claim status codes (835).
CLAIM_PAYMENT_STATUS = {
    "1": "Processed as primary",
    "2": "Processed as secondary",
    "3": "Processed as tertiary",
    "4": "Denied",
    "19": "Processed as primary, forwarded to additional payer",
    "20": "Processed as secondary, forwarded to additional payer",
    "21": "Processed as tertiary, forwarded to additional payer",
    "22": "Reversal of previous payment",
    "23": "Not our claim, forwarded to additional payer",
    "25": "Predetermination pricing only, no payment",
}
PAID_STATUSES = {"1", "2", "3", "19", "20", "21"}

# CAS claim adjustment group codes.
GROUP_CODES = {
    "CO": "Contractual obligation: the provider writes this off; you are not billed for it",
    "PR": "Patient responsibility",
    "OA": "Other adjustment",
    "PI": "Payer-initiated reduction",
    "CR": "Correction or reversal",
}

# Common claim adjustment reason codes, in plain language for staff and patients.
CARC = {
    "1": "Deductible: this amount counts toward your deductible.",
    "2": "Coinsurance: your share of the cost after the deductible.",
    "3": "Copay: the fixed amount your plan sets for this kind of visit.",
    "4": "The procedure code doesn't match the modifier used. The office can correct and resubmit.",
    "16": "The claim was missing information or had an error. The office can correct and resubmit it.",
    "18": "This is a duplicate of a claim that was already sent.",
    "22": "Another insurance plan may need to pay first (coordination of benefits).",
    "23": "Adjusted because of what another payer already paid.",
    "26": "The service happened before your coverage started.",
    "27": "The service happened after your coverage ended.",
    "29": "The claim was sent after the plan's filing deadline.",
    "31": "The payer couldn't find you as a member of this plan.",
    "45": "The charge is more than the plan's contracted rate. The difference is written off.",
    "50": "The plan decided this service wasn't medically necessary.",
    "96": "This service isn't covered by your plan.",
    "97": "This service is included in the payment for another service on the same day.",
    "109": "This payer doesn't cover this claim. It may belong to a different plan.",
    "119": "You've reached the plan's benefit maximum for this service.",
    "146": "The diagnosis code on the claim was not valid for the date of service.",
    "167": "The plan doesn't cover this diagnosis.",
    "197": "The plan needed a prior authorization for this service and none was on file.",
    "204": "This service isn't covered under your current benefit plan.",
    "242": "The service was not provided by an in-network provider.",
    "253": "A federal sequestration reduction was applied to the payment.",
}

# PLB provider-level adjustment reason codes.
PLB_REASONS = {
    "72": "Authorized return",
    "B2": "Rebate",
    "CS": "Adjustment",
    "FB": "Forwarding balance",
    "L6": "Interest owed",
    "WO": "Overpayment recovery",
}


def carc_text(code: str) -> str:
    return CARC.get(code, f"Adjustment reason code {code}.")


def adjustment_label(group: str, code: str) -> str:
    group_label = GROUP_CODES.get(group, group).split(":")[0]
    return f"{group}-{code} ({group_label}): {carc_text(code)}"


def service_type_label(code: str) -> str:
    return SERVICE_TYPES.get(code, f"Service type {code}")


# --- Identifiers ----------------------------------------------------------------------------------


def npi_check_digit(first9: str) -> str:
    """Luhn check digit over the 80840 prefix plus the first nine NPI digits (CMS NPI standard)."""
    digits = [int(c) for c in "80840" + first9]
    total = 0
    for i, dgt in enumerate(reversed(digits)):
        if i % 2 == 0:
            dgt *= 2
            if dgt > 9:
                dgt -= 9
        total += dgt
    return str((10 - total % 10) % 10)


def npi_valid(npi: str | None) -> bool:
    return bool(npi) and bool(re.fullmatch(r"[12]\d{9}", npi or "")) and npi_check_digit(npi[:9]) == npi[9]


ICD10_PATTERN = re.compile(r"^[A-TV-Z][0-9][0-9A-Z](\.?[0-9A-Z]{1,4})?$")
PROCEDURE_PATTERN = re.compile(r"^[0-9A-Z]{5}$")


def icd10_valid(code: str) -> bool:
    return bool(ICD10_PATTERN.match(code.strip().upper()))


def icd10_x12(code: str) -> str:
    """ICD-10-CM codes travel without the dot: E78.5 -> E785."""
    return code.strip().upper().replace(".", "")


def icd10_display(code: str) -> str:
    """E785 -> E78.5."""
    code = code.strip().upper().replace(".", "")
    return code if len(code) <= 3 else f"{code[:3]}.{code[3:]}"
