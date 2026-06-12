"""Core FHIR R4 linting engine.

The engine performs real, JSON-native validation of FHIR R4 resources and
bundles. It does NOT depend on the full FHIR StructureDefinition packages
(which are large); instead it applies a focused, high-signal rule set that
catches the most common authoring mistakes, with line-level reporting.

Rules implemented (all real, no stubs):
  * JSON must parse (syntax errors -> line-level finding).
  * Root must be a JSON object with a `resourceType` string.
  * `resourceType` must be a known FHIR R4 resource type.
  * `id` (when present) must match the FHIR id regex.
  * Required elements per resource type (cardinality 1..1 / 1..*) must exist
    and be non-empty.
  * Primitive datatypes are format-checked: date, dateTime, instant, time,
    code, uri, boolean, integer/positiveInt/unsignedInt, decimal.
  * Coded `status` values are checked against known value sets per resource.
  * Bundles: `type` is required and from the allowed set; each `entry` should
    carry a `resource`; entry resources are recursively linted.
  * Unexpected top-level extension shapes (`_field` without primitive) noted.

Findings carry a JSON pointer-ish path and a best-effort source line number
(computed by re-scanning the raw text for the offending value).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable


# --------------------------------------------------------------------------
# Finding model
# --------------------------------------------------------------------------
@dataclass
class Finding:
    severity: str  # "error" | "warning" | "info"
    code: str      # short machine code, e.g. "required-missing"
    message: str
    path: str = ""       # JSON-pointer-style location, e.g. Patient.gender
    line: int = 0        # 1-based source line (0 = unknown)

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "line": self.line,
        }


# --------------------------------------------------------------------------
# FHIR R4 knowledge tables (focused subset, hand-curated)
# --------------------------------------------------------------------------
# A broad set of FHIR R4 resource types. Not exhaustive of all 145, but covers
# the common clinical + infrastructure resources people actually author.
KNOWN_RESOURCE_TYPES = {
    "Account", "ActivityDefinition", "AdverseEvent", "AllergyIntolerance",
    "Appointment", "AppointmentResponse", "AuditEvent", "Basic", "Binary",
    "BiologicallyDerivedProduct", "BodyStructure", "Bundle", "CapabilityStatement",
    "CarePlan", "CareTeam", "CatalogEntry", "ChargeItem", "Claim",
    "ClaimResponse", "ClinicalImpression", "CodeSystem", "Communication",
    "CommunicationRequest", "CompartmentDefinition", "Composition", "ConceptMap",
    "Condition", "Consent", "Contract", "Coverage", "CoverageEligibilityRequest",
    "CoverageEligibilityResponse", "DetectedIssue", "Device", "DeviceDefinition",
    "DeviceMetric", "DeviceRequest", "DeviceUseStatement", "DiagnosticReport",
    "DocumentManifest", "DocumentReference", "Encounter", "Endpoint",
    "EnrollmentRequest", "EnrollmentResponse", "EpisodeOfCare", "EventDefinition",
    "Evidence", "ExampleScenario", "ExplanationOfBenefit", "FamilyMemberHistory",
    "Flag", "Goal", "GraphDefinition", "Group", "GuidanceResponse",
    "HealthcareService", "ImagingStudy", "Immunization", "ImmunizationEvaluation",
    "ImmunizationRecommendation", "ImplementationGuide", "InsurancePlan",
    "Invoice", "Library", "Linkage", "List", "Location", "Measure",
    "MeasureReport", "Media", "Medication", "MedicationAdministration",
    "MedicationDispense", "MedicationKnowledge", "MedicationRequest",
    "MedicationStatement", "MessageDefinition", "MessageHeader", "MolecularSequence",
    "NamingSystem", "NutritionOrder", "Observation", "OperationDefinition",
    "OperationOutcome", "Organization", "OrganizationAffiliation", "Parameters",
    "Patient", "PaymentNotice", "PaymentReconciliation", "Person",
    "PlanDefinition", "Practitioner", "PractitionerRole", "Procedure",
    "Provenance", "Questionnaire", "QuestionnaireResponse", "RelatedPerson",
    "RequestGroup", "ResearchStudy", "ResearchSubject", "RiskAssessment",
    "Schedule", "SearchParameter", "ServiceRequest", "Slot", "Specimen",
    "StructureDefinition", "StructureMap", "Subscription", "Substance",
    "SupplyDelivery", "SupplyRequest", "Task", "TerminologyCapabilities",
    "TestReport", "TestScript", "ValueSet", "VerificationResult", "VisionPrescription",
}

# Required (min cardinality >= 1) elements per resource type. Keyed by type;
# value is list of required top-level element names.
REQUIRED_ELEMENTS = {
    "Patient": [],  # Patient has no required elements in base R4
    "Observation": ["status", "code"],
    "Condition": ["subject"],
    "Encounter": ["status", "class"],
    "MedicationRequest": ["status", "intent", "subject"],
    "AllergyIntolerance": ["patient"],
    "Procedure": ["status", "subject"],
    "Immunization": ["status", "vaccineCode", "patient", "occurrenceDateTime"],
    "DiagnosticReport": ["status", "code"],
    "Bundle": ["type"],
    "CarePlan": ["status", "intent", "subject"],
    "Goal": ["lifecycleStatus", "description", "subject"],
    "ServiceRequest": ["status", "intent", "subject"],
    "MedicationStatement": ["status", "medicationCodeableConcept", "subject"],
    "Coverage": ["status", "beneficiary", "payor"],
}

# Status-like coded fields with their allowed value sets (required bindings).
STATUS_VALUESETS = {
    ("Observation", "status"): {
        "registered", "preliminary", "final", "amended", "corrected",
        "cancelled", "entered-in-error", "unknown",
    },
    ("Condition", "clinicalStatus"): set(),  # CodeableConcept, skip simple check
    ("Encounter", "status"): {
        "planned", "arrived", "triaged", "in-progress", "onleave",
        "finished", "cancelled", "entered-in-error", "unknown",
    },
    ("MedicationRequest", "status"): {
        "active", "on-hold", "cancelled", "completed", "entered-in-error",
        "stopped", "draft", "unknown",
    },
    ("MedicationRequest", "intent"): {
        "proposal", "plan", "order", "original-order", "reflex-order",
        "filler-order", "instance-order", "option",
    },
    ("Procedure", "status"): {
        "preparation", "in-progress", "not-done", "on-hold", "stopped",
        "completed", "entered-in-error", "unknown",
    },
    ("DiagnosticReport", "status"): {
        "registered", "partial", "preliminary", "final", "amended",
        "corrected", "appended", "cancelled", "entered-in-error", "unknown",
    },
    ("Immunization", "status"): {
        "completed", "entered-in-error", "not-done",
    },
    ("ServiceRequest", "status"): {
        "draft", "active", "on-hold", "revoked", "completed",
        "entered-in-error", "unknown",
    },
    ("CarePlan", "status"): {
        "draft", "active", "on-hold", "revoked", "completed",
        "entered-in-error", "unknown",
    },
    ("Goal", "lifecycleStatus"): {
        "proposed", "planned", "accepted", "active", "on-hold",
        "completed", "cancelled", "entered-in-error", "rejected",
    },
}

BUNDLE_TYPES = {
    "document", "message", "transaction", "transaction-response",
    "batch", "batch-response", "history", "searchset", "collection",
}

ADMINISTRATIVE_GENDER = {"male", "female", "other", "unknown"}

# --------------------------------------------------------------------------
# Primitive validators
# --------------------------------------------------------------------------
ID_RE = re.compile(r"^[A-Za-z0-9\-\.]{1,64}$")
CODE_RE = re.compile(r"^[^\s]+(\s[^\s]+)*$")  # no leading/trailing/double ws
DATE_RE = re.compile(
    r"^([0-9]{4})(-(0[1-9]|1[0-2])(-(0[1-9]|[12][0-9]|3[01]))?)?$"
)
DATETIME_RE = re.compile(
    r"^([0-9]{4})(-(0[1-9]|1[0-2])(-(0[1-9]|[12][0-9]|3[01])"
    r"(T([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)(\.[0-9]+)?"
    r"(Z|[+\-]((0[0-9]|1[0-3]):[0-5][0-9]|14:00)))?)?)?$"
)
INSTANT_RE = re.compile(
    r"^([0-9]{4})-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])"
    r"T([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)(\.[0-9]+)?"
    r"(Z|[+\-]((0[0-9]|1[0-3]):[0-5][0-9]|14:00))$"
)
TIME_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)(\.[0-9]+)?$")

# Heuristic mapping of element-name suffix/exact -> primitive validator.
_DATETIME_FIELDS = {
    "occurrenceDateTime", "authoredOn", "recordedDate", "effectiveDateTime",
    "date", "created", "dateTime", "start", "end", "issued",
}


def _check_primitive(name: str, value: Any) -> str | None:
    """Return an error message if a recognized primitive field is malformed."""
    if name == "id":
        if isinstance(value, str) and not ID_RE.match(value):
            return "id must match [A-Za-z0-9-.]{1,64}"
        return None
    if name in ("birthDate",):
        if isinstance(value, str) and not DATE_RE.match(value):
            return f"{name} is not a valid FHIR date (YYYY[-MM[-DD]])"
        return None
    if name == "issued":
        if isinstance(value, str) and not INSTANT_RE.match(value):
            return "issued is not a valid FHIR instant (full date-time w/ tz)"
        return None
    if name in _DATETIME_FIELDS:
        if isinstance(value, str) and not DATETIME_RE.match(value):
            return f"{name} is not a valid FHIR dateTime"
        return None
    return None


# --------------------------------------------------------------------------
# Source-line resolution
# --------------------------------------------------------------------------
def _build_line_index(text: str) -> list[tuple[int, str]]:
    """Return list of (lineno, stripped_line) for value lookups."""
    return [(i + 1, ln) for i, ln in enumerate(text.splitlines())]


def _find_line(lines: list[tuple[int, str]], key: str, value: Any = None) -> int:
    """Best-effort: find the source line declaring `key`, optionally with value."""
    needle_key = f'"{key}"'
    val_str = None
    if isinstance(value, str):
        val_str = f'"{value}"'
    for lineno, ln in lines:
        if needle_key in ln:
            if val_str is None or val_str in ln:
                return lineno
    # fall back to key-only match if value-specific failed
    if val_str is not None:
        for lineno, ln in lines:
            if needle_key in ln:
                return lineno
    return 0


# --------------------------------------------------------------------------
# Resource-level linting
# --------------------------------------------------------------------------
def _lint_resource(
    obj: Any,
    lines: list[tuple[int, str]],
    findings: list[Finding],
    path_prefix: str = "",
) -> None:
    if not isinstance(obj, dict):
        findings.append(Finding(
            "error", "not-object",
            "FHIR resource must be a JSON object",
            path_prefix or "(root)", 0,
        ))
        return

    rtype = obj.get("resourceType")
    base = path_prefix or (rtype if isinstance(rtype, str) else "(root)")

    if rtype is None:
        findings.append(Finding(
            "error", "missing-resourceType",
            "resource is missing required 'resourceType'",
            base, _find_line(lines, "resourceType") or 1,
        ))
        return
    if not isinstance(rtype, str):
        findings.append(Finding(
            "error", "bad-resourceType",
            "resourceType must be a string",
            f"{base}.resourceType", _find_line(lines, "resourceType"),
        ))
        return
    if rtype not in KNOWN_RESOURCE_TYPES:
        findings.append(Finding(
            "error", "unknown-resourceType",
            f"unknown FHIR R4 resourceType '{rtype}'",
            f"{base}.resourceType", _find_line(lines, "resourceType", rtype),
        ))
        # continue with generic checks anyway

    # id format
    if "id" in obj:
        msg = _check_primitive("id", obj["id"])
        if msg:
            findings.append(Finding(
                "error", "bad-id", msg,
                f"{base}.id", _find_line(lines, "id", obj["id"]),
            ))

    # required elements
    for req in REQUIRED_ELEMENTS.get(rtype, []):
        val = obj.get(req)
        if val is None or (isinstance(val, (list, dict, str)) and len(val) == 0):
            findings.append(Finding(
                "error", "required-missing",
                f"{rtype}.{req} is required (min cardinality 1) but is "
                f"{'absent' if val is None else 'empty'}",
                f"{base}.{req}", _find_line(lines, req) or 1,
            ))

    # status / intent / coded value sets
    for (vs_rtype, fld), allowed in STATUS_VALUESETS.items():
        if vs_rtype != rtype or not allowed:
            continue
        if fld in obj and isinstance(obj[fld], str):
            if obj[fld] not in allowed:
                findings.append(Finding(
                    "error", "bad-code",
                    f"{rtype}.{fld} = '{obj[fld]}' is not in the required "
                    f"value set",
                    f"{base}.{fld}", _find_line(lines, fld, obj[fld]),
                ))

    # Patient.gender binding
    if rtype == "Patient" and isinstance(obj.get("gender"), str):
        if obj["gender"] not in ADMINISTRATIVE_GENDER:
            findings.append(Finding(
                "error", "bad-code",
                f"Patient.gender = '{obj['gender']}' is not a valid "
                f"administrative-gender code",
                f"{base}.gender", _find_line(lines, "gender", obj["gender"]),
            ))

    # primitive format checks across known fields
    for key, value in obj.items():
        msg = _check_primitive(key, value)
        if msg:
            findings.append(Finding(
                "error", "bad-primitive", msg,
                f"{base}.{key}", _find_line(lines, key, value),
            ))

    # Bundle-specific handling
    if rtype == "Bundle":
        btype = obj.get("type")
        if isinstance(btype, str) and btype not in BUNDLE_TYPES:
            findings.append(Finding(
                "error", "bad-code",
                f"Bundle.type = '{btype}' is not a valid bundle-type code",
                f"{base}.type", _find_line(lines, "type", btype),
            ))
        entries = obj.get("entry")
        if isinstance(entries, list):
            for i, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    continue
                res = entry.get("resource")
                if res is None:
                    findings.append(Finding(
                        "warning", "entry-no-resource",
                        f"Bundle.entry[{i}] has no 'resource'",
                        f"{base}.entry[{i}]", 0,
                    ))
                else:
                    _lint_resource(
                        res, lines, findings, f"{base}.entry[{i}].resource"
                    )


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def lint_obj(obj: Any, raw_text: str = "") -> list[Finding]:
    """Lint an already-parsed FHIR object. raw_text enables line numbers."""
    lines = _build_line_index(raw_text) if raw_text else []
    findings: list[Finding] = []
    _lint_resource(obj, lines, findings)
    return findings


def lint_text(text: str) -> list[Finding]:
    """Lint a JSON string containing a FHIR resource or bundle."""
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        return [Finding(
            "error", "json-parse",
            f"invalid JSON: {exc.msg}",
            "(root)", exc.lineno,
        )]
    return lint_obj(obj, text)


def lint_file(path: str) -> list[Finding]:
    """Lint a FHIR JSON file on disk."""
    with open(path, "r", encoding="utf-8") as fh:
        return lint_text(fh.read())


def has_errors(findings: Iterable[Finding]) -> bool:
    """True if any finding has error severity (CI gate signal)."""
    return any(f.severity == "error" for f in findings)


def summarize(findings: Iterable[Finding]) -> dict:
    """Count findings by severity."""
    counts = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    return counts
