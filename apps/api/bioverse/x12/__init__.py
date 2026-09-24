"""X12 5010 EDI: envelopes, 270/271 eligibility, 837P claims, 277CA acknowledgments, 835 remittances.

Pure Python, no dependencies, no database access. Builders take the Pydantic models in `models`, parsers
return them, and every problem surfaces as an `X12Error` whose `errors` are readable sentences.
"""

from bioverse.x12.ack import build_277ca, parse_277ca
from bioverse.x12.claim import build_837p, parse_837p, validate_837p
from bioverse.x12.core import Delimiters, Envelope, X12Error, parse_interchange
from bioverse.x12.eligibility import build_270, build_271, parse_270, parse_271
from bioverse.x12.remit import build_835, parse_835

__all__ = [
    "Delimiters", "Envelope", "X12Error", "parse_interchange",
    "build_270", "parse_270", "build_271", "parse_271",
    "build_837p", "parse_837p", "validate_837p",
    "build_277ca", "parse_277ca",
    "build_835", "parse_835",
]
