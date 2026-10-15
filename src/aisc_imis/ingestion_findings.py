"""Build a single review report from the four membership-source adapters.

The adapters deliberately keep their own small result types.  This module is
the boundary that turns those results into one stable, serializable review
format; it does not change source files or make membership decisions.
"""

from __future__ import annotations

import hashlib
import html
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from aisc_imis.normalization_contracts import EvidenceRecord, ValidationRejection

CATEGORIES = ("rejected", "partial", "duplicate", "conflict", "unknown_code", "other")
CODE_FIELDS = {"Member Type", "Status", "Change Type", "Activity Type"}


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
class IngestionFindingsReport:
    """A report that can be written as JSON or rendered for human review."""

    sources: tuple[SourceSummary, ...]
    findings: tuple[Finding, ...]

    def to_dict(self) -> dict[str, object]:
        category_counts = {category: 0 for category in CATEGORIES}
        for finding in self.findings:
            category_counts[finding.category] += 1
        return {
            "sources": [summary.to_dict() for summary in self.sources],
            "category_counts": category_counts,
            "findings": [finding.to_dict() for finding in self.findings],
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
    return IngestionFindingsReport(tuple(summaries), tuple(all_findings))


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


def _markdown_value(value: str) -> str:
    return html.escape(value).replace("|", "\\|").replace("\n", "<br>")
