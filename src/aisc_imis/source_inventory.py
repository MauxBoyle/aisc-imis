"""Build privacy-safe, aggregate-only inventories of CSV source files."""

from __future__ import annotations

import csv
import hashlib
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


class SourceInventoryError(ValueError):
    """Raised when an inventory source cannot be profiled safely."""


@dataclass(frozen=True)
class SourceDefinition:
    """Configuration for one CSV input, including its aggregate-only checks."""

    name: str
    path: Path
    source_type: str
    candidate_key: tuple[str, ...]
    date_columns: tuple[str, ...]
    required_columns: tuple[str, ...]
    extraction_note: str


@dataclass(frozen=True)
class NullPattern:
    """A set of blank columns and the number of rows with that pattern."""

    columns: tuple[str, ...]
    row_count: int


@dataclass(frozen=True)
class CandidateKeyStats:
    """Completeness and uniqueness counts for a configured candidate key."""

    columns: tuple[str, ...]
    complete_rows: int
    distinct_complete_keys: int
    duplicate_complete_rows: int


@dataclass(frozen=True)
class DateCoverage:
    """Aggregate parse and range findings for one date column."""

    nonblank_values: int
    parsed_values: int
    unparseable_values: int
    earliest: str | None
    latest: str | None
    implausible_values: int


@dataclass(frozen=True)
class SourceResult:
    """Aggregate results for one source; source cell values are never retained."""

    definition: SourceDefinition
    headers: tuple[str, ...]
    row_count: int
    null_counts: dict[str, int]
    null_patterns: tuple[NullPattern, ...]
    candidate_key: CandidateKeyStats
    date_coverage: dict[str, DateCoverage]


@dataclass(frozen=True)
class Inventory:
    """The aggregate-only results for all configured sources."""

    sources: tuple[SourceResult, ...]
    reference_date: date


def build_inventory(
    definitions: Iterable[SourceDefinition], *, reference_date: date | None = None
) -> Inventory:
    """Profile configured CSV files without retaining member-level row data."""
    effective_reference_date = reference_date or date.today()
    return Inventory(
        sources=tuple(
            _profile_source(definition, effective_reference_date)
            for definition in definitions
        ),
        reference_date=effective_reference_date,
    )


def _profile_source(definition: SourceDefinition, reference_date: date) -> SourceResult:
    if not definition.path.is_file():
        raise SourceInventoryError(
            f"Configured source does not exist: {definition.path}"
        )

    with definition.path.open(encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        headers = tuple(reader.fieldnames or ())
        configured_columns = dict.fromkeys(
            (
                *definition.required_columns,
                *definition.candidate_key,
                *definition.date_columns,
            )
        )
        missing = [column for column in configured_columns if column not in headers]
        if missing:
            raise SourceInventoryError(
                f"Source {definition.name!r} is missing required columns: "
                + ", ".join(missing)
            )

        null_counts = Counter({header: 0 for header in headers})
        null_patterns: Counter[tuple[str, ...]] = Counter()
        complete_key_digests: set[bytes] = set()
        complete_rows = 0
        date_values: dict[str, list[date]] = {
            column: [] for column in definition.date_columns
        }
        date_nonblank = Counter()
        date_unparseable = Counter()
        date_implausible = Counter()
        row_count = 0

        for row in reader:
            row_count += 1
            blank_columns = tuple(
                header for header in headers if not (row.get(header) or "").strip()
            )
            null_counts.update(blank_columns)
            null_patterns[blank_columns] += 1

            key = tuple(
                (row.get(column) or "").strip() for column in definition.candidate_key
            )
            if all(key):
                complete_rows += 1
                complete_key_digests.add(_digest_key(key))

            for column in definition.date_columns:
                value = (row.get(column) or "").strip()
                if not value:
                    continue
                date_nonblank[column] += 1
                parsed = _parse_date(value)
                if parsed is None:
                    date_unparseable[column] += 1
                    continue
                date_values[column].append(parsed)
                if parsed.year < 1900 or parsed > reference_date:
                    date_implausible[column] += 1

    coverage = {
        column: DateCoverage(
            nonblank_values=date_nonblank[column],
            parsed_values=len(date_values[column]),
            unparseable_values=date_unparseable[column],
            earliest=min(date_values[column]).isoformat()
            if date_values[column]
            else None,
            latest=max(date_values[column]).isoformat()
            if date_values[column]
            else None,
            implausible_values=date_implausible[column],
        )
        for column in definition.date_columns
    }
    patterns = tuple(
        NullPattern(columns=columns, row_count=count)
        for columns, count in sorted(
            null_patterns.items(), key=lambda item: (-item[1], item[0])
        )
    )
    return SourceResult(
        definition=definition,
        headers=headers,
        row_count=row_count,
        null_counts=dict(null_counts),
        null_patterns=patterns,
        candidate_key=CandidateKeyStats(
            columns=definition.candidate_key,
            complete_rows=complete_rows,
            distinct_complete_keys=len(complete_key_digests),
            duplicate_complete_rows=complete_rows - len(complete_key_digests),
        ),
        date_coverage=coverage,
    )


def _parse_date(value: str) -> date | None:
    """Parse common iMIS export date formats without raising on bad values."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for date_format in (
        "%m/%d/%Y",
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %I:%M %p",
    ):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue
    return None


def _digest_key(key: tuple[str, ...]) -> bytes:
    """Return a non-reversible, unambiguous digest for an in-memory key count."""
    digest = hashlib.sha256()
    for value in key:
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.digest()


def render_markdown(inventory: Inventory) -> str:
    """Render documented aggregate findings, deliberately excluding source values."""
    lines = [
        "# Membership source inventory",
        "",
        "This version-controlled inventory contains schema and aggregate findings only. "
        "It does not retain or publish member rows, IDs, names, contact details, or "
        "other source cell values.",
        "",
        "## Scope and limitations",
        "",
        "The inventory reports observed file coverage, not business interpretations. "
        "The CSContactBasic history file contains older snapshot observations, but "
        "historical completeness cannot be assumed. Date anomalies are retained as "
        "findings; this process does not silently correct them.",
        "",
        f"Date plausibility rule: parsed dates before 1900 or after {inventory.reference_date.isoformat()} are flagged.",
        "",
    ]
    for result in inventory.sources:
        definition = result.definition
        lines.extend(
            [
                f"## {definition.name}",
                "",
                f"- Source type: {definition.source_type}",
                f"- Local input path: `{definition.path.as_posix()}`",
                f"- Extraction / derivation: {definition.extraction_note}",
                f"- Rows: {result.row_count}",
                f"- Headers ({len(result.headers)}): "
                + ", ".join(f"`{header}`" for header in result.headers),
                "",
                "### Null findings",
                "",
                "| Column | Blank rows |",
                "| --- | ---: |",
            ]
        )
        lines.extend(
            f"| `{column}` | {result.null_counts[column]} |"
            for column in result.headers
        )
        lines.extend(["", "Most common blank-column patterns (up to five):", ""])
        for pattern in result.null_patterns[:5]:
            label = ", ".join(f"`{column}`" for column in pattern.columns) or "none"
            lines.append(f"- {pattern.row_count} rows: {label}")
        key = result.candidate_key
        lines.extend(
            [
                "",
                "### Candidate-key findings",
                "",
                "- Candidate key: "
                + ", ".join(f"`{column}`" for column in key.columns),
                f"- Complete key rows: {key.complete_rows}",
                f"- Distinct complete keys: {key.distinct_complete_keys}",
                f"- Duplicate complete-key rows: {key.duplicate_complete_rows}",
                "",
                "### Date coverage",
                "",
                "| Column | Nonblank | Parsed | Unparseable | Earliest | Latest | Implausible |",
                "| --- | ---: | ---: | ---: | --- | --- | ---: |",
            ]
        )
        for column, coverage in result.date_coverage.items():
            lines.append(
                f"| `{column}` | {coverage.nonblank_values} | {coverage.parsed_values} | "
                f"{coverage.unparseable_values} | {coverage.earliest or '—'} | "
                f"{coverage.latest or '—'} | {coverage.implausible_values} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Retention boundary",
            "",
            "The source exports remain local operational files under ignored `data/raw/` "
            "and `data/processed/` directories. This Markdown file is the committed "
            "source of truth for the aggregate inventory; regenerate it from authorized "
            "local exports when inputs change.",
            "",
        ]
    )
    return "\n".join(lines)
