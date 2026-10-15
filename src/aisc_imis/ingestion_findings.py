"""Build a single review report from the four membership-source adapters.

The adapters deliberately keep their own small result types.  This module is
the boundary that turns those results into one stable, serializable review
format; it does not change source files or make membership decisions.
"""

from __future__ import annotations

import hashlib
import html
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from aisc_imis.normalization_contracts import EvidenceRecord, ValidationRejection

CATEGORIES = ("rejected", "partial", "duplicate", "conflict", "unknown_code", "other")
CODE_FIELDS = {"Member Type", "Status", "Change Type", "Activity Type"}
REPORTING_MEMBER_TYPES = frozenset({"ACT", "ASSOC", "PROF", "AFF", "STU", "EDU"})
PROVISIONAL_GRID_NOTICE = (
    "These provisional consistency grids are review aids, not validated business rules. "
    "Revisit them at the earliest opportunity before using them to exclude members or "
    "change source data."
)


class AdapterResult(Protocol):
    """The shared portion of the four adapter result objects."""

    observations: tuple[object, ...]
    rejections: tuple[ValidationRejection, ...]
    findings: tuple[object, ...]


@dataclass(frozen=True)
class Finding:
    """One machine-readable item for a reviewer to investigate."""

    id: str
    category: str
    code: str
    message: str
    source: str
    source_file: str | None
    row_reference: str | None
    field: str | None
    raw_fields: dict[str, str | None] | None
    validation_failures: tuple[dict[str, str], ...] = ()

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["validation_failures"] = list(self.validation_failures)
        return result


@dataclass(frozen=True)
class SourceSummary:
    """Counts for one adapter input, including rows accepted downstream."""

    source: str
    accepted_observations: int
    rejected_rows: int
    findings: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class TandemGrid:
    """Aggregate 2x2 comparison of two provisional state indicators."""

    source: str
    row_label: str
    column_label: str
    row_true_column_true: int
    row_true_column_false: int
    row_false_column_true: int
    row_false_column_false: int
    excluded_observations: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class IngestionFindingsReport:
    """A report that can be written as JSON or rendered for human review."""

    sources: tuple[SourceSummary, ...]
    findings: tuple[Finding, ...]
    tandem_grids: tuple[TandemGrid, ...]

    def to_dict(self) -> dict[str, object]:
        category_counts = {category: 0 for category in CATEGORIES}
        for finding in self.findings:
            category_counts[finding.category] += 1
        return {
            "sources": [summary.to_dict() for summary in self.sources],
            "category_counts": category_counts,
            "findings": [finding.to_dict() for finding in self.findings],
            "provisional_grid_notice": PROVISIONAL_GRID_NOTICE,
            "tandem_grids": [grid.to_dict() for grid in self.tandem_grids],
        }

    def to_json(self) -> str:
        """Return stable, nicely formatted JSON suitable for local review."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"

    def to_markdown(self) -> str:
        """Render all report evidence safely for a local Markdown review file."""
        lines = [
            "# Ingestion findings",
            "",
            "This local report can contain member-level source data. Do not commit it.",
            "",
            "## Source summary",
            "",
            "| Source | Accepted observations | Rejected rows | Findings |",
            "| --- | ---: | ---: | ---: |",
        ]
        lines.extend(
            "| {source} | {accepted_observations} | {rejected_rows} | {findings} |".format(
                **summary.to_dict()
            )
            for summary in self.sources
        )
        lines.extend(
            [
                "",
                "## Findings by category",
                "",
                "| Category | Count |",
                "| --- | ---: |",
            ]
        )
        counts = self.to_dict()["category_counts"]
        assert isinstance(counts, dict)
        lines.extend(f"| {category} | {counts[category]} |" for category in CATEGORIES)
        lines.extend(
            [
                "",
                "## Provisional state-consistency grids",
                "",
                PROVISIONAL_GRID_NOTICE,
            ]
        )
        for grid in self.tandem_grids:
            lines.extend(
                [
                    "",
                    f"### {grid.source}: {grid.row_label} and {grid.column_label}",
                    "",
                    f"| {grid.row_label} | {grid.column_label}=True | {grid.column_label}=False |",
                    "| --- | ---: | ---: |",
                    f"| True | {grid.row_true_column_true} | {grid.row_true_column_false} |",
                    f"| False | {grid.row_false_column_true} | {grid.row_false_column_false} |",
                    f"Excluded because a needed value was missing or unparsed: {grid.excluded_observations}.",
                ]
            )
        lines.extend(
            [
                "",
                "## Review items",
                "",
                "| ID | Category | Source row | Field | Message |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for finding in self.findings:
            row = finding.row_reference or "batch"
            lines.append(
                "| {id} | {category} | {source} / {row} | {field} | {message} |".format(
                    id=finding.id,
                    category=finding.category,
                    source=_markdown_value(finding.source),
                    row=_markdown_value(row),
                    field=_markdown_value(finding.field or ""),
                    message=_markdown_value(finding.message),
                )
            )
        for finding in self.findings:
            lines.extend(["", f"### {finding.id}", ""])
            if finding.source_file:
                lines.append(f"Source file: {_markdown_value(finding.source_file)}  ")
            if finding.raw_fields is not None:
                lines.extend(["Raw fields:", "", "```json"])
                lines.append(
                    html.escape(
                        json.dumps(finding.raw_fields, indent=2, ensure_ascii=False),
                        quote=False,
                    )
                )
                lines.append("```")
            if finding.validation_failures:
                lines.extend(["Validation failures:", "", "```json"])
                lines.append(
                    html.escape(
                        json.dumps(list(finding.validation_failures), indent=2, ensure_ascii=False),
                        quote=False,
                    )
                )
                lines.append("```")
        return "\n".join(lines) + "\n"


def build_ingestion_findings_report(
    *,
    current: AdapterResult,
    historical: AdapterResult,
    membership_changes: AdapterResult,
    activity_history: AdapterResult,
) -> IngestionFindingsReport:
    """Combine adapter results without removing accepted observations.

    The source names here are canonical report names, rather than user-chosen
    filenames, so a finding's ID stays stable when the same export is renamed.
    """
    results: tuple[tuple[str, AdapterResult], ...] = (
        ("current", current),
        ("historical", historical),
        ("membership_changes", membership_changes),
        ("activity_history", activity_history),
    )
    summaries: list[SourceSummary] = []
    all_findings: list[Finding] = []
    tandem_grids: list[TandemGrid] = []
    occurrences: dict[tuple[str, str, str, str, str], int] = {}
    for source, result in results:
        source_findings = _source_findings(source, result, occurrences)
        summaries.append(
            SourceSummary(
                source=source,
                accepted_observations=len(result.observations),
                rejected_rows=len(result.rejections),
                findings=len(source_findings),
            )
        )
        all_findings.extend(source_findings)
        tandem_grids.extend(_tandem_grids(source, result.observations))
    return IngestionFindingsReport(
        tuple(summaries), tuple(all_findings), tuple(tandem_grids)
    )


def write_ingestion_findings_report(
    report: IngestionFindingsReport, output_directory: Path | str
) -> tuple[Path, Path]:
    """Write the JSON and Markdown versions and return their paths."""
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    json_path = output_directory / "ingestion-findings.json"
    markdown_path = output_directory / "ingestion-findings.md"
    json_path.write_text(report.to_json(), encoding="utf-8")
    markdown_path.write_text(report.to_markdown(), encoding="utf-8")
    return json_path, markdown_path


def _source_findings(
    source: str,
    result: AdapterResult,
    occurrences: dict[tuple[str, str, str, str, str], int],
) -> list[Finding]:
    raw_by_reference = {
        observation.record.reference: _raw_fields(observation.record)
        for observation in result.observations
        if hasattr(observation, "record") and isinstance(observation.record, EvidenceRecord)
    }
    output: list[Finding] = []
    for rejection in result.rejections:
        failures = tuple(asdict(failure) for failure in rejection.failures)
        output.append(
            _make_finding(
                source=source,
                category="rejected",
                code="validation_rejected",
                message="Row was rejected by structural validation.",
                reference=rejection.reference,
                field=None,
                raw_fields=_raw_fields(rejection),
                validation_failures=failures,
                occurrences=occurrences,
            )
        )
    for adapter_finding in result.findings:
        reference = getattr(adapter_finding, "reference", None)
        field = getattr(adapter_finding, "field", None)
        code = adapter_finding.code
        output.append(
            _make_finding(
                source=source,
                category=_category(code, field),
                code=code,
                message=adapter_finding.message,
                reference=reference,
                field=field,
                raw_fields=raw_by_reference.get(reference),
                validation_failures=(),
                occurrences=occurrences,
            )
        )
    return output


def _make_finding(
    *,
    source: str,
    category: str,
    code: str,
    message: str,
    reference: object | None,
    field: str | None,
    raw_fields: dict[str, str | None] | None,
    validation_failures: tuple[dict[str, str], ...],
    occurrences: dict[tuple[str, str, str, str, str], int],
) -> Finding:
    source_file = getattr(reference, "source_name", None)
    row_reference = getattr(reference, "row_reference", None)
    occurrence_key = (source, row_reference or "", category, code, field or "")
    occurrence = occurrences.get(occurrence_key, 0) + 1
    occurrences[occurrence_key] = occurrence
    identifier_input = {
        "source": source,
        "row_reference": row_reference,
        "category": category,
        "code": code,
        "field": field,
        "occurrence": occurrence,
    }
    identifier = hashlib.sha256(
        json.dumps(identifier_input, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return Finding(
        id=identifier,
        category=category,
        code=code,
        message=message,
        source=source,
        source_file=source_file,
        row_reference=row_reference,
        field=field,
        raw_fields=raw_fields,
        validation_failures=validation_failures,
    )


def _raw_fields(record: EvidenceRecord | ValidationRejection) -> dict[str, str | None]:
    return {field.name: field.value for field in record.raw_fields}


def _category(code: str, field: str | None) -> str:
    """Map adapter details to stable broad buckets for triage."""
    if code.startswith("duplicate_"):
        return "duplicate"
    if "conflict" in code:
        return "conflict"
    if code.startswith(("unmapped_", "unresolved_")) or (
        code == "invalid" and field in CODE_FIELDS
    ):
        return "unknown_code"
    if code == "invalid" or code == "missing_observation_date":
        return "partial"
    return "other"


def _tandem_grids(source: str, observations: tuple[object, ...]) -> tuple[TandemGrid, ...]:
    """Compare provisional state indicators without making a membership decision."""
    current_or_historical = (
        _tandem_grid(
            source, observations, "reporting Member Type", "Status is A",
            _is_reporting_member_type, _is_active_status,
        ),
        _tandem_grid(
            source, observations, "reporting Member Type", "Is Member is True",
            _is_reporting_member_type, _is_member,
        ),
        _tandem_grid(
            source, observations, "Status is A", "Is Member is True",
            _is_active_status, _is_member,
        ),
        _tandem_grid(
            source, observations, "Is Company is True", "Member Type ends in D (dependent)",
            _is_company, _is_dependent_member_type,
        ),
    )
    if source in {"current", "historical"}:
        return current_or_historical
    if source == "membership_changes":
        return current_or_historical[:1]
    if source == "activity_history":
        return current_or_historical[3:]
    return ()


def _tandem_grid(
    source: str,
    observations: tuple[object, ...],
    row_label: str,
    column_label: str,
    row_value: Callable[[object], bool | None],
    column_value: Callable[[object], bool | None],
) -> TandemGrid:
    """Count parsed boolean predicates in a grid, excluding unknown inputs."""
    counts = {(True, True): 0, (True, False): 0, (False, True): 0, (False, False): 0}
    excluded = 0
    for observation in observations:
        row = row_value(observation)
        column = column_value(observation)
        if row is None or column is None:
            excluded += 1
            continue
        counts[(row, column)] += 1
    return TandemGrid(
        source=source,
        row_label=row_label,
        column_label=column_label,
        row_true_column_true=counts[(True, True)],
        row_true_column_false=counts[(True, False)],
        row_false_column_true=counts[(False, True)],
        row_false_column_false=counts[(False, False)],
        excluded_observations=excluded,
    )


def _is_reporting_member_type(observation: object) -> bool | None:
    member_type = getattr(observation, "member_type", None)
    return member_type in REPORTING_MEMBER_TYPES if member_type is not None else None


def _is_active_status(observation: object) -> bool | None:
    status = getattr(observation, "status", None)
    return status == "A" if status is not None else None


def _is_member(observation: object) -> bool | None:
    return getattr(observation, "is_member", None)


def _is_company(observation: object) -> bool | None:
    return getattr(observation, "is_company", None)


def _is_dependent_member_type(observation: object) -> bool | None:
    member_type = getattr(observation, "member_type", None)
    return member_type.endswith("D") if member_type is not None else None


def _markdown_value(value: str) -> str:
    return html.escape(value).replace("|", "\\|").replace("\n", "<br>")
