"""Read membership-change CSV evidence without inferring lifecycle events.

This Python-facing adapter keeps each structurally valid transaction beside its
parsed values.  Taxonomy mappings are review configuration: they can identify
an unresolved or conflicting meaning, but never create a lifecycle fact.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from aisc_imis.normalization_contracts import (
    MembershipChange,
    SourceReference,
    ValidationRejection,
    validate_membership_change,
)
from aisc_imis.normalization_parsers import (
    ParsedValue,
    ParseFinding,
    ParseResult,
    parse_date,
    parse_identifier,
    parse_member_type,
    parse_status,
)

REQUIRED_HEADERS = (
    "ChangeID",
    "Ordinal",
    "Change Type",
    "Member Type",
    "ChangeUpdate",
    "ChangeCreated",
    "Status",
)
TAXONOMY_FILENAME = "lifecycle-evidence-taxonomy.csv"
TAXONOMY_SOURCE = "Membership changes"
TAXONOMY_FIELD = "Change Type"


@dataclass(frozen=True)
class IngestionFinding:
    """A batch- or row-level issue found while reading a change export."""

    code: str
    message: str
    reference: SourceReference | None = None
    field: str | None = None


@dataclass(frozen=True)
class MembershipChangeObservation:
    """One structurally valid membership-change row and parsed source values.

    The three dates remain separate source evidence.  They are not ordered,
    reconciled, or used to derive a lifecycle transition.
    """

    record: MembershipChange
    change_id: str
    ordinal: str
    change_type: str
    member_type: str | None
    change_update: ParsedValue | None
    change_created: ParsedValue | None
    status: str | None
    change_effective: ParsedValue | None


@dataclass(frozen=True)
class MembershipChangeRecordsResult:
    """All observations, structural rejections, and ingestion findings."""

    observations: tuple[MembershipChangeObservation, ...]
    rejections: tuple[ValidationRejection, ...]
    findings: tuple[IngestionFinding, ...]


@dataclass(frozen=True)
class _TaxonomyMapping:
    draft_lifecycle_name: str
    countability_effect: str


def read_membership_change_records(
    csv_path: Path | str, reference_directory: Path | str
) -> MembershipChangeRecordsResult:
    """Read a local membership-change export with reviewed codebooks.

    The function neither writes files, joins transactions to members, nor
    infers a lifecycle transition.  ``reference_directory`` supplies the
    reviewed member-type, status, and lifecycle-taxonomy configuration.
    """
    csv_path = Path(csv_path)
    reference_directory = Path(reference_directory)
    member_types, member_type_findings = _load_codebook(
        reference_directory / "member_types.csv"
    )
    statuses, status_findings = _load_codebook(reference_directory / "statuses.csv")
    taxonomy, taxonomy_findings = _load_taxonomy(
        reference_directory / TAXONOMY_FILENAME
    )
    findings = [*member_type_findings, *status_findings, *taxonomy_findings]
    if findings:
        return MembershipChangeRecordsResult((), (), tuple(findings))

    try:
        source_file = csv_path.open(encoding="utf-8-sig", newline="")
    except OSError as error:
        return MembershipChangeRecordsResult(
            (),
            (),
            (
                IngestionFinding(
                    code="source_unreadable",
                    message=f"Could not read membership-change CSV: {error}",
                ),
            ),
        )

    with source_file:
        reader = csv.DictReader(source_file)
        headers = reader.fieldnames or []
        missing_headers = [header for header in REQUIRED_HEADERS if header not in headers]
        if missing_headers:
            return MembershipChangeRecordsResult(
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

        observations: list[MembershipChangeObservation] = []
        rejections: list[ValidationRejection] = []
        for row in reader:
            reference = SourceReference(
                source_name=csv_path.name,
                row_reference=f"row-{reader.line_num}",
            )
            source_row = _source_row(row)
            outcome = validate_membership_change(source_row, reference)
            if isinstance(outcome, ValidationRejection):
                rejections.append(outcome)
                continue

            change_id = parse_identifier(outcome.change_id)
            ordinal = parse_identifier(outcome.ordinal)
            # Structural validation guarantees these required values are nonblank.
            assert change_id.normalized is not None
            assert ordinal.normalized is not None
            change_type = parse_identifier(outcome.change_type)
            assert change_type.normalized is not None
            member_type = parse_member_type(outcome.member_type, member_types)
            status = parse_status(outcome.status, statuses)
            change_update = parse_date(outcome.change_update)
            change_created = parse_date(outcome.change_created)
            change_effective = _parse_optional_date(outcome.change_effective)
            for field, value_findings in (
                ("ChangeID", change_id.findings),
                ("Ordinal", ordinal.findings),
                ("Change Type", change_type.findings),
                ("Member Type", member_type.findings),
                ("ChangeUpdate", change_update.findings),
                ("ChangeCreated", change_created.findings),
                ("Status", status.findings),
                ("ChangeEffective", change_effective.findings),
            ):
                findings.extend(_parse_findings(reference, field, value_findings))
            findings.extend(_taxonomy_findings(reference, change_type.normalized, taxonomy))
            observations.append(
                MembershipChangeObservation(
                    record=outcome,
                    change_id=change_id.normalized,
                    ordinal=ordinal.normalized,
                    change_type=change_type.normalized,
                    member_type=member_type.normalized,
                    change_update=change_update.normalized,
                    change_created=change_created.normalized,
                    status=status.normalized,
                    change_effective=change_effective.normalized,
                )
            )

    findings.extend(_duplicate_findings(observations))
    return MembershipChangeRecordsResult(
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
) -> tuple[Mapping[str, tuple[_TaxonomyMapping, ...]], tuple[IngestionFinding, ...]]:
    required_headers = (
        "source",
        "field",
        "code",
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
        mappings: dict[str, list[_TaxonomyMapping]] = defaultdict(list)
        for row in reader:
            if row.get("source") != TAXONOMY_SOURCE or row.get("field") != TAXONOMY_FIELD:
                continue
            code = row.get("code")
            if not isinstance(code, str) or not code.strip():
                continue
            mappings[code.strip()].append(
                _TaxonomyMapping(
                    draft_lifecycle_name=(row.get("draft_lifecycle_name") or "").strip(),
                    countability_effect=(row.get("countability_effect") or "").strip(),
                )
            )
    return {code: tuple(values) for code, values in mappings.items()}, ()


def _source_row(row: Mapping[str | None, str | list[str] | None]) -> dict[str, str | None]:
    """Keep all named CSV columns in supplied order and with supplied values."""
    return {
        name: value if isinstance(value, str) or value is None else None
        for name, value in row.items()
        if isinstance(name, str)
    }


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


def _taxonomy_findings(
    reference: SourceReference,
    change_type: str,
    taxonomy: Mapping[str, tuple[_TaxonomyMapping, ...]],
) -> list[IngestionFinding]:
    mappings = taxonomy.get(change_type, ())
    if not mappings:
        return [
            IngestionFinding(
                code="unmapped_change_type",
                message=(
                    "Change Type has no reviewed Membership changes / Change Type "
                    f"taxonomy mapping: {change_type!r}."
                ),
                reference=reference,
                field="Change Type",
            )
        ]
    if len(set(mappings)) != 1:
        return [
            IngestionFinding(
                code="conflicting_change_type_mapping",
                message=(
                    "Change Type has conflicting reviewed Membership changes / "
                    f"Change Type taxonomy mappings: {change_type!r}."
                ),
                reference=reference,
                field="Change Type",
            )
        ]
    mapping = mappings[0]
    if (
        mapping.draft_lifecycle_name == "unknown"
        or mapping.countability_effect == "unresolved"
    ):
        return [
            IngestionFinding(
                code="unresolved_change_type_mapping",
                message=(
                    "Change Type has an unresolved reviewed Membership changes / "
                    f"Change Type taxonomy mapping: {change_type!r}."
                ),
                reference=reference,
                field="Change Type",
            )
        ]
    return []


def _duplicate_findings(
    observations: list[MembershipChangeObservation],
) -> list[IngestionFinding]:
    by_key: dict[tuple[str, str], list[MembershipChangeObservation]] = defaultdict(list)
    for observation in observations:
        by_key[(observation.change_id, observation.ordinal)].append(observation)

    findings: list[IngestionFinding] = []
    for change_id, ordinal in by_key:
        matching_observations = by_key[(change_id, ordinal)]
        if len(matching_observations) > 1:
            findings.extend(
                IngestionFinding(
                    code="duplicate_transaction_key",
                    message=(
                        "ChangeID and Ordinal appear in more than one membership "
                        f"change row: ({change_id!r}, {ordinal!r})."
                    ),
                    reference=observation.record.reference,
                    field="ChangeID",
                )
                for observation in matching_observations
            )
    return findings
