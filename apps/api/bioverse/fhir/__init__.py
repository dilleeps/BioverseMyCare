"""FHIR R4 mapping for Bioverse.

`resources` turns rows from the Bioverse tables into FHIR R4 resources (plain dicts, JSON-ready).
`store` reads a patient's record and hands rows to those mappers. The HTTP surface is
routers/fhir.py. Every mapper emits only what the record holds: nothing is inferred, and a result
explanation appears (as DiagnosticReport.conclusion) only after a clinician approved it.
"""

FHIR_VERSION = "4.0.1"
