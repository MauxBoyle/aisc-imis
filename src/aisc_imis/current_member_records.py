"""Read current-member CSV evidence without making lifecycle decisions.

This is a Python-facing adapter, rather than a command-line interface.  It
keeps each accepted source row beside parsed present-state values and reports
problems as data for a later reviewer.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from aisc_imis.normalization_contracts import (
    CurrentRecord,
    SourceReference,
    ValidationRejection,
    validate_current_record,
)
from aisc_imis.normalization_parsers import (
    ParsedValue,
    ParseFinding,
    ParseResult,
    parse_boolean,
    parse_date,
    parse_identifier,
    parse_member_type,
    parse_status,
)

REQUIRED_HEADERS = ("iMIS Id", "Member Type", "Is Company", "Is Member", "Last Updated")


@dataclass(frozen=True)
class IngestionFinding:
    """A batch- or row-level issue found while reading an export."""

    code: str
    message: str
    reference: SourceReference | None = None
    field: str | None = None


@dataclass(frozen=True)
class CurrentMemberObservation:
    """One structurally valid current-state row and its parsed values.

    A ``None`` parsed value is not a claim about the member.  Consult the
    result findings and the retained ``record`` raw fields to see why it could
    not be normalized.
    """

    record: CurrentRecord
    imis_id: str
    member_type: str | None
    is_company: bool | None
    is_member: bool | None
    last_updated: ParsedValue | None
    status: str | None
    category: str | None


@dataclass(frozen=True)
class CurrentMemberRecordsResult:
    """All observations, structural rejections, and ingestion findings."""

    observations: tuple[CurrentMemberObservation, ...]
    rejections: tuple[ValidationRejection, ...]
    findings: tuple[IngestionFinding, ...]


def read_current_member_records(
    csv_path: Path | str, reference_directory: Path | str
) -> CurrentMemberRecordsResult:
    """Read a current-state CSV using reviewed member-type and status tables.

    ``csv_path`` and ``reference_directory`` are explicit so callers choose
    their authorized local inputs.  The adapter neither writes data nor
    deduplicates or infers membership transitions.
    """
    csv_path = Path(csv_path)
    reference_directory = Path(reference_directory)
    member_types, member_type_findings = _load_codebook(
        reference_directory / "member_types.csv"
    )
    statuses, status_findings = _load_codebook(reference_directory / "statuses.csv")
    findings = [*member_type_findings, *status_findings]
    if findings:
        return CurrentMemberRecordsResult((), (), tuple(findings))

    try:
        source_file = csv_path.open(encoding="utf-8-sig", newline="")
    except OSError as error:
        return CurrentMemberRecordsResult(
            (),
            (),
            (
                IngestionFinding(
                    code="source_unreadable",
                    message=f"Could not read current-member CSV: {error}",
                ),
            ),
        )

    with source_file:
        reader = csv.DictReader(source_file)
        headers = reader.fieldnames or []
        missing_headers = [header for header in REQUIRED_HEADERS if header not in headers]
        if missing_headers:
            return CurrentMemberRecordsResult(
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

        observations: list[CurrentMemberObservation] = []
        rejections: list[ValidationRejection] = []
        for row in reader:
            reference = SourceReference(
                source_name=csv_path.name,
                row_reference=f"row-{reader.line_num}",
            )
            source_row = _source_row(row)
            outcome = validate_current_record(source_row, reference)
            if isinstance(outcome, ValidationRejection):
                rejections.append(outcome)
                continue

            identifier = parse_identifier(outcome.imis_id)
            # Structural validation already guarantees a nonblank identifier.
            assert identifier.normalized is not None
            member_type = parse_member_type(outcome.member_type, member_types)
            is_company = parse_boolean(outcome.is_company)
            is_member = parse_boolean(outcome.is_member)
            last_updated = parse_date(outcome.last_updated)
            status = _parse_optional_status(outcome.status, statuses)
            category = _parse_optional_text(outcome.category)
            parse_results = (
                ("iMIS Id", identifier.findings),
                ("Member Type", member_type.findings),
                ("Is Company", is_company.findings),
                ("Is Member", is_member.findings),
                ("Last Updated", last_updated.findings),
                ("Status", status.findings),
                ("Category", category.findings),
            )
            for field, value_findings in parse_results:
                findings.extend(_parse_findings(reference, field, value_findings))
            observations.append(
                CurrentMemberObservation(
                    record=outcome,
                    imis_id=identifier.normalized,
                    member_type=member_type.normalized,
                    is_company=is_company.normalized,
                    is_member=is_member.normalized,
                    last_updated=last_updated.normalized,
                    status=status.normalized,
                    category=category.normalized,
                )
            )

    findings.extend(_duplicate_findings(observations))
    return CurrentMemberRecordsResult(
        observations=tuple(observations),
        rejections=tuple(rejections),
        findings=tuple(findings),
    )


def _load_codebook(path: Path) -> tuple[Mapping[str, object], tuple[IngestionFinding, ...]]:
    """Load the reviewed ``code`` column without assigning meaning to it."""
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


def _source_row(row: Mapping[str | None, str | list[str] | None]) -> dict[str, str | None]:
    """Keep all named CSV columns in their supplied order and values."""
    return {
        name: value if isinstance(value, str) or value is None else None
        for name, value in row.items()
        if isinstance(name, str)
    }


def _parse_optional_status(
    raw: str | None, codebook: Mapping[str, object]
) -> ParseResult[str]:
    """A blank optional status is absent evidence, not a blank-value error."""
    if raw is None or not raw.strip():
        return ParseResult(raw=raw, normalized=None)
    return parse_status(raw, codebook)


def _parse_optional_text(raw: str | None) -> ParseResult[str]:
    return ParseResult(raw=raw, normalized=raw.strip() if raw and raw.strip() else None)


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


def _duplicate_findings(
    observations: list[CurrentMemberObservation],
) -> list[IngestionFinding]:
    by_identifier: dict[str, list[CurrentMemberObservation]] = defaultdict(list)
    for observation in observations:
        by_identifier[observation.imis_id].append(observation)

    findings: list[IngestionFinding] = []
    for identifier, matching_observations in by_identifier.items():
        if len(matching_observations) > 1:
            findings.extend(
                IngestionFinding(
                    code="duplicate_imis_id",
                    message=(
                        "Normalized iMIS Id appears in more than one current "
                        f"export row: {identifier!r}."
                    ),
                    reference=observation.record.reference,
                    field="iMIS Id",
                )
                for observation in matching_observations
            )
    return findings
