"""Read activity-history CSV evidence without deriving membership status.

Activity rows can be useful review evidence, including payment evidence, but
they are never enough for this adapter to assert a membership transition.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from aisc_imis.normalization_contracts import (
    ActivityRecord,
    SourceReference,
    ValidationRejection,
    validate_activity_record,
)
from aisc_imis.normalization_parsers import (
    ParsedValue,
    ParseFinding,
    ParseResult,
    parse_boolean,
    parse_date,
    parse_identifier,
    parse_member_type,
)

REQUIRED_HEADERS = (
    "iMIS Id",
    "Sequence",
    "A_Transaction",
    "Activity Type",
    "Effective Date",
    "Member Type",
    "Is a Company",
)
TAXONOMY_FILENAME = "lifecycle-evidence-taxonomy.csv"
TAXONOMY_SOURCE = "Activity history"
TAXONOMY_FIELD = "Activity Type"
EXTRA_FIELD_PREFIX = "__extra_csv_value_"


@dataclass(frozen=True)
class IngestionFinding:
    """A batch- or row-level issue found while reading activity history."""

    code: str
    message: str
    reference: SourceReference | None = None
    field: str | None = None


@dataclass(frozen=True)
class ActivityClassification:
    """A reviewed taxonomy classification, not a membership-state conclusion."""

    evidence_class: str
    assertion_level: str
    draft_lifecycle_name: str
    countability_effect: str


@dataclass(frozen=True)
class ActivityHistoryObservation:
    """One structurally valid activity row and separately parsed evidence.

    ``activity_classification`` is reviewed taxonomy configuration. It may
    identify payment activity or a lifecycle candidate, but it never changes
    or asserts a member's status.
    """

    record: ActivityRecord
    imis_id: str
    sequence: str
    transaction: str
    activity_type: str
    effective_date: ParsedValue | None
    member_type: str | None
    is_company: bool | None
    transaction_date: ParsedValue | None
    activity_classification: ActivityClassification | None


@dataclass(frozen=True)
class ActivityHistoryRecordsResult:
    """All observations, structural rejections, and ingestion findings."""

    observations: tuple[ActivityHistoryObservation, ...]
    rejections: tuple[ValidationRejection, ...]
    findings: tuple[IngestionFinding, ...]


def read_activity_history_records(
    csv_path: Path | str, reference_directory: Path | str
) -> ActivityHistoryRecordsResult:
    """Read a local activity-history CSV using reviewed codebooks and taxonomy.

    The reader preserves each structurally valid row in CSV order. It does not
    write files, deduplicate transactions, reconcile dates, join members, or
    infer a membership transition from an activity, including a payment.
    """
    csv_path = Path(csv_path)
    reference_directory = Path(reference_directory)
    member_types, member_type_findings = _load_codebook(
        reference_directory / "member_types.csv"
    )
    taxonomy, taxonomy_findings = _load_taxonomy(
        reference_directory / TAXONOMY_FILENAME
    )
    findings = [*member_type_findings, *taxonomy_findings]
    if findings:
        return ActivityHistoryRecordsResult((), (), tuple(findings))

    try:
        source_file = csv_path.open(encoding="utf-8-sig", newline="")
    except OSError as error:
        return ActivityHistoryRecordsResult(
            (),
            (),
            (
                IngestionFinding(
                    code="source_unreadable",
                    message=f"Could not read activity-history CSV: {error}",
                ),
            ),
        )

    with source_file:
        reader = csv.DictReader(source_file)
        headers = reader.fieldnames or []
        missing_headers = [header for header in REQUIRED_HEADERS if header not in headers]
        if missing_headers:
            return ActivityHistoryRecordsResult(
                (),
                (),
                tuple(
                    IngestionFinding(
                        code="missing_required_header",
                        message=f"Required CSV header is missing: {header}.",
                        field=header,
                    )
                    for header in missing_headers
                ),
            )
        if _incompatible_headers(headers):
            return ActivityHistoryRecordsResult(
                (),
                (),
                (
                    IngestionFinding(
                        code="incompatible_source_schema",
                        message="CSV headers are blank or duplicated.",
                    ),
                ),
            )

        observations: list[ActivityHistoryObservation] = []
        rejections: list[ValidationRejection] = []
        for row in reader:
            reference = SourceReference(
                source_name=csv_path.name,
                row_reference=f"row-{reader.line_num}",
            )
            if row.get(None):
                findings.append(
                    IngestionFinding(
                        code="incompatible_source_schema",
                        message="CSV row has more values than its header defines.",
                        reference=reference,
                    )
                )
            outcome = validate_activity_record(_source_row(row), reference)
            if isinstance(outcome, ValidationRejection):
                rejections.append(outcome)
                continue

            imis_id = parse_identifier(outcome.imis_id)
            sequence = parse_identifier(outcome.sequence)
            transaction = parse_identifier(outcome.transaction)
            activity_type = parse_identifier(outcome.activity_type)
            assert imis_id.normalized is not None
            assert sequence.normalized is not None
            assert transaction.normalized is not None
            assert activity_type.normalized is not None
            member_type = parse_member_type(outcome.member_type, member_types)
            is_company = parse_boolean(outcome.is_company)
            effective_date = parse_date(outcome.effective_date)
            transaction_date = _parse_optional_date(outcome.transaction_date)
            for field, value_findings in (
                ("iMIS Id", imis_id.findings),
                ("Sequence", sequence.findings),
                ("A_Transaction", transaction.findings),
                ("Activity Type", activity_type.findings),
                ("Member Type", member_type.findings),
                ("Is a Company", is_company.findings),
                ("Effective Date", effective_date.findings),
                ("Transaction Date", transaction_date.findings),
            ):
                findings.extend(_parse_findings(reference, field, value_findings))

            classification, classification_findings = _classify_activity_type(
                reference, activity_type.normalized, taxonomy
            )
            findings.extend(classification_findings)
            observations.append(
                ActivityHistoryObservation(
                    record=outcome,
                    imis_id=imis_id.normalized,
                    sequence=sequence.normalized,
                    transaction=transaction.normalized,
                    activity_type=activity_type.normalized,
                    effective_date=effective_date.normalized,
                    member_type=member_type.normalized,
                    is_company=is_company.normalized,
                    transaction_date=transaction_date.normalized,
                    activity_classification=classification,
                )
            )

    findings.extend(_duplicate_findings(observations))
    return ActivityHistoryRecordsResult(
        observations=tuple(observations),
        rejections=tuple(rejections),
        findings=tuple(findings),
    )


def _load_codebook(path: Path) -> tuple[Mapping[str, object], tuple[IngestionFinding, ...]]:
    try:
        source_file = path.open(encoding="utf-8-sig", newline="")
    except OSError as error:
        return {}, (
            IngestionFinding(
                code="reference_unreadable",
                message=f"Could not read reviewed reference table {path.name}: {error}",
                field=path.name,
            ),
        )
    with source_file:
        reader = csv.DictReader(source_file)
        if "code" not in (reader.fieldnames or []):
            return {}, (
                IngestionFinding(
                    code="reference_missing_code_header",
                    message=f"Reviewed reference table {path.name} has no code header.",
                    field=path.name,
                ),
            )
        return {
            code.strip(): row
            for row in reader
            if isinstance((code := row.get("code")), str) and code.strip()
        }, ()


def _load_taxonomy(
    path: Path,
) -> tuple[Mapping[str, tuple[ActivityClassification, ...]], tuple[IngestionFinding, ...]]:
    required_headers = (
        "source",
        "field",
        "code",
        "evidence_class",
        "assertion_level",
        "draft_lifecycle_name",
        "countability_effect",
    )
    try:
        source_file = path.open(encoding="utf-8-sig", newline="")
    except OSError as error:
        return {}, (
            IngestionFinding(
                code="reference_unreadable",
                message=f"Could not read reviewed reference table {path.name}: {error}",
                field=path.name,
            ),
        )
    with source_file:
        reader = csv.DictReader(source_file)
        missing_headers = [
            header for header in required_headers if header not in (reader.fieldnames or [])
        ]
        if missing_headers:
            return {}, tuple(
                IngestionFinding(
                    code="reference_missing_taxonomy_header",
                    message=f"Reviewed taxonomy table {path.name} has no {header} header.",
                    field=header,
                )
                for header in missing_headers
            )
        mappings: dict[str, list[ActivityClassification]] = defaultdict(list)
        for row in reader:
            if row.get("source") != TAXONOMY_SOURCE or row.get("field") != TAXONOMY_FIELD:
                continue
            code = row.get("code")
            if not isinstance(code, str) or not code.strip():
                continue
            mappings[code.strip()].append(
                ActivityClassification(
                    evidence_class=(row.get("evidence_class") or "").strip(),
                    assertion_level=(row.get("assertion_level") or "").strip(),
                    draft_lifecycle_name=(row.get("draft_lifecycle_name") or "").strip(),
                    countability_effect=(row.get("countability_effect") or "").strip(),
                )
            )
    return {code: tuple(values) for code, values in mappings.items()}, ()


def _source_row(row: Mapping[str | None, str | list[str] | None]) -> dict[str, str | None]:
    """Keep named values in order and retain surplus CSV cells as raw fields."""
    source_row = {
        name: value if isinstance(value, str) or value is None else None
        for name, value in row.items()
        if isinstance(name, str)
    }
    extra_values = row.get(None)
    if isinstance(extra_values, list):
        for index, value in enumerate(extra_values, start=1):
            field_name = f"{EXTRA_FIELD_PREFIX}{index}"
            while field_name in source_row:
                field_name += "_"
            source_row[field_name] = value
    return source_row


def _parse_optional_date(raw: str | None) -> ParseResult[ParsedValue]:
    if raw is None or not raw.strip():
        return ParseResult(raw=raw, normalized=None)
    return parse_date(raw)


def _parse_findings(
    reference: SourceReference, field: str, parse_findings: tuple[ParseFinding, ...]
) -> list[IngestionFinding]:
    return [
        IngestionFinding(
            code=finding.code,
            message=finding.message,
            reference=reference,
            field=field,
        )
        for finding in parse_findings
    ]


def _classify_activity_type(
    reference: SourceReference,
    activity_type: str,
    taxonomy: Mapping[str, tuple[ActivityClassification, ...]],
) -> tuple[ActivityClassification | None, list[IngestionFinding]]:
    mappings = taxonomy.get(activity_type, ())
    if not mappings:
        return None, [
            IngestionFinding(
                code="unmapped_activity_type",
                message=(
                    "Activity Type has no reviewed Activity history / Activity Type "
                    f"taxonomy mapping: {activity_type!r}."
                ),
                reference=reference,
                field="Activity Type",
            )
        ]
    if len(set(mappings)) != 1:
        return None, [
            IngestionFinding(
                code="conflicting_activity_type_mapping",
                message=(
                    "Activity Type has conflicting reviewed Activity history / "
                    f"Activity Type taxonomy mappings: {activity_type!r}."
                ),
                reference=reference,
                field="Activity Type",
            )
        ]
    mapping = mappings[0]
    if (
        mapping.draft_lifecycle_name == "unknown"
        or mapping.countability_effect == "unresolved"
    ):
        return mapping, [
            IngestionFinding(
                code="unresolved_activity_type_mapping",
                message=(
                    "Activity Type has an unresolved reviewed Activity history / "
                    f"Activity Type taxonomy mapping: {activity_type!r}."
                ),
                reference=reference,
                field="Activity Type",
            )
        ]
    return mapping, []


def _duplicate_findings(
    observations: list[ActivityHistoryObservation],
) -> list[IngestionFinding]:
    by_key: dict[tuple[str, str], list[ActivityHistoryObservation]] = defaultdict(list)
    for observation in observations:
        by_key[(observation.imis_id, observation.sequence)].append(observation)

    findings: list[IngestionFinding] = []
    for imis_id, sequence in by_key:
        matching_observations = by_key[(imis_id, sequence)]
        if len(matching_observations) > 1:
            findings.extend(
                IngestionFinding(
                    code="duplicate_member_sequence",
                    message=(
                        "iMIS Id and Sequence appear in more than one activity "
                        f"row: ({imis_id!r}, {sequence!r})."
                    ),
                    reference=observation.record.reference,
                    field="iMIS Id",
                )
                for observation in matching_observations
            )
    return findings


def _incompatible_headers(headers: list[str]) -> bool:
    return any(not header for header in headers) or len(headers) != len(set(headers))
