"""Read combined historical CSV evidence without inferring lifecycle events.

The combined legacy export has no per-row capture timestamp.  This adapter
keeps the source's ``Last Updated`` value separate from a configured snapshot
coverage date so downstream code cannot mistake either one for a membership
transition date.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from aisc_imis.normalization_contracts import (
    SnapshotObservation,
    SourceReference,
    ValidationRejection,
    validate_snapshot_observation,
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
SNAPSHOT_DATE_HEADER = "snapshot_date"
OBSERVATION_DATE_BASIS = "configured_snapshot_on_or_after_last_updated"
EXTRA_FIELD_PREFIX = "__extra_csv_value_"


@dataclass(frozen=True)
class IngestionFinding:
    """A batch- or row-level issue found while reading a legacy export."""

    code: str
    message: str
    reference: SourceReference | None = None
    field: str | None = None


@dataclass(frozen=True)
class HistoricalSnapshotObservation:
    """One structurally valid legacy row and its parsed evidence.

    ``observation_date`` is configured coverage, not a source event date.
    It is derived only from ``last_updated`` and the reviewed schedule.  A
    ``None`` parsed value makes no claim about the member; consult findings and
    the raw ``record`` fields for the supplied evidence.
    """

    record: SnapshotObservation
    imis_id: str
    member_type: str | None
    is_company: bool | None
    is_member: bool | None
    last_updated: ParsedValue | None
    status: str | None
    category: str | None
    observation_date: date | None
    observation_date_basis: str | None


@dataclass(frozen=True)
class HistoricalSnapshotRecordsResult:
    """All observations, structural rejections, and ingestion findings."""

    observations: tuple[HistoricalSnapshotObservation, ...]
    rejections: tuple[ValidationRejection, ...]
    findings: tuple[IngestionFinding, ...]


def read_historical_snapshot_records(
    csv_path: Path | str, reference_directory: Path | str
) -> HistoricalSnapshotRecordsResult:
    """Read a combined historical CSV with reviewed codes and snapshot coverage.

    The function only reads caller-selected local files.  It neither modifies
    the snapshot merge nor deduplicates evidence or infers membership changes.
    """
    csv_path = Path(csv_path)
    reference_directory = Path(reference_directory)
    member_types, member_type_findings = _load_codebook(
        reference_directory / "member_types.csv"
    )
    statuses, status_findings = _load_codebook(reference_directory / "statuses.csv")
    snapshot_dates, snapshot_date_findings = _load_snapshot_dates(
        reference_directory / "snapshot_dates.csv"
    )
    findings = [*member_type_findings, *status_findings, *snapshot_date_findings]
    if findings:
        return HistoricalSnapshotRecordsResult((), (), tuple(findings))

    try:
        source_file = csv_path.open(encoding="utf-8-sig", newline="")
    except OSError as error:
        return HistoricalSnapshotRecordsResult(
            (),
            (),
            (
                IngestionFinding(
                    code="source_unreadable",
                    message=f"Could not read historical snapshot CSV: {error}",
                ),
            ),
        )

    with source_file:
        reader = csv.DictReader(source_file)
        headers = reader.fieldnames or []
        missing_headers = [header for header in REQUIRED_HEADERS if header not in headers]
        if missing_headers:
            return HistoricalSnapshotRecordsResult(
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
            return HistoricalSnapshotRecordsResult(
                (),
                (),
                (
                    IngestionFinding(
                        code="incompatible_source_schema",
                        message="CSV headers are blank or duplicated.",
                    ),
                ),
            )

        observations: list[HistoricalSnapshotObservation] = []
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
            source_row = _source_row(row)
            outcome = validate_snapshot_observation(source_row, reference)
            if isinstance(outcome, ValidationRejection):
                rejections.append(outcome)
                continue

            identifier = parse_identifier(outcome.imis_id)
            assert identifier.normalized is not None
            member_type = parse_member_type(outcome.member_type, member_types)
            is_company = parse_boolean(outcome.is_company)
            is_member = parse_boolean(outcome.is_member)
            last_updated = parse_date(outcome.last_updated)
            status = _parse_optional_status(outcome.status, statuses)
            category = _parse_optional_text(outcome.category)
            for field, value_findings in (
                ("iMIS Id", identifier.findings),
                ("Member Type", member_type.findings),
                ("Is Company", is_company.findings),
                ("Is Member", is_member.findings),
                ("Last Updated", last_updated.findings),
                ("Status", status.findings),
                ("Category", category.findings),
            ):
                findings.extend(_parse_findings(reference, field, value_findings))

            observation_date = _observation_date(last_updated.normalized, snapshot_dates)
            if observation_date is None:
                findings.append(
                    IngestionFinding(
                        code="missing_observation_date",
                        message=(
                            "No configured snapshot date is available on or after "
                            "the parsed Last Updated value."
                        ),
                        reference=reference,
                        field="Last Updated",
                    )
                )
            observations.append(
                HistoricalSnapshotObservation(
                    record=outcome,
                    imis_id=identifier.normalized,
                    member_type=member_type.normalized,
                    is_company=is_company.normalized,
                    is_member=is_member.normalized,
                    last_updated=last_updated.normalized,
                    status=status.normalized,
                    category=category.normalized,
                    observation_date=observation_date,
                    observation_date_basis=(
                        OBSERVATION_DATE_BASIS if observation_date is not None else None
                    ),
                )
            )

    findings.extend(_conflict_findings(observations))
    return HistoricalSnapshotRecordsResult(
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


def _load_snapshot_dates(path: Path) -> tuple[tuple[date, ...], tuple[IngestionFinding, ...]]:
    """Load configured coverage dates without interpreting them as event dates."""
    try:
        source_file = path.open(encoding="utf-8-sig", newline="")
    except OSError as error:
        return (), (
            IngestionFinding(
                code="reference_unreadable",
                message=f"Could not read reviewed reference table {path.name}: {error}",
                field=path.name,
            ),
        )

    with source_file:
        reader = csv.DictReader(source_file)
        if SNAPSHOT_DATE_HEADER not in (reader.fieldnames or []):
            return (), (
                IngestionFinding(
                    code="reference_missing_snapshot_date_header",
                    message=(
                        f"Reviewed reference table {path.name} has no "
                        f"{SNAPSHOT_DATE_HEADER} header."
                    ),
                    field=path.name,
                ),
            )
        dates: list[date] = []
        findings: list[IngestionFinding] = []
        for row in reader:
            parsed = parse_date(row.get(SNAPSHOT_DATE_HEADER))
            if parsed.normalized is None:
                findings.extend(
                    IngestionFinding(
                        code="reference_invalid_snapshot_date",
                        message=finding.message,
                        field=SNAPSHOT_DATE_HEADER,
                    )
                    for finding in parsed.findings
                )
                continue
            dates.append(_calendar_date(parsed.normalized))
        if not dates and not findings:
            findings.append(
                IngestionFinding(
                    code="reference_invalid_snapshot_date",
                    message="Reviewed snapshot-date schedule has no dates.",
                    field=SNAPSHOT_DATE_HEADER,
                )
            )
        return tuple(sorted(set(dates))), tuple(findings)


def _source_row(row: Mapping[str | None, str | list[str] | None]) -> dict[str, str | None]:
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


def _parse_optional_status(
    raw: str | None, codebook: Mapping[str, object]
) -> ParseResult[str]:
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


def _incompatible_headers(headers: list[str]) -> bool:
    return any(not header.strip() for header in headers) or len(set(headers)) != len(headers)


def _observation_date(
    last_updated: ParsedValue | None, snapshot_dates: tuple[date, ...]
) -> date | None:
    if last_updated is None:
        return None
    updated_day = _calendar_date(last_updated)
    return next((snapshot_date for snapshot_date in snapshot_dates if snapshot_date >= updated_day), None)


def _calendar_date(value: ParsedValue) -> date:
    return value.date() if isinstance(value, datetime) else value


def _conflict_findings(
    observations: list[HistoricalSnapshotObservation],
) -> list[IngestionFinding]:
    """Report conflicting state evidence without selecting or dropping a row."""
    by_key: dict[tuple[str, ParsedValue], list[HistoricalSnapshotObservation]] = defaultdict(list)
    for observation in observations:
        if observation.last_updated is not None:
            by_key[(observation.imis_id, observation.last_updated)].append(observation)

    findings: list[IngestionFinding] = []
    for (identifier, last_updated), matches in by_key.items():
        states = {
            (
                observation.member_type,
                observation.is_company,
                observation.is_member,
                observation.status,
            )
            for observation in matches
        }
        if len(states) > 1:
            findings.extend(
                IngestionFinding(
                    code="conflicting_snapshot_observation",
                    message=(
                        "Rows with the same normalized iMIS Id and parsed Last "
                        f"Updated disagree on observed state fields: {identifier!r}, "
                        f"{last_updated!r}."
                    ),
                    reference=observation.record.reference,
                )
                for observation in matches
            )
    return findings
