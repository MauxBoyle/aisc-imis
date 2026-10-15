"""Discover membership-lifecycle evidence without publishing member-level data."""

from __future__ import annotations

import csv
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


class LifecycleDiscoveryError(ValueError):
    """Raised when a lifecycle source cannot be safely profiled."""


@dataclass(frozen=True)
class LifecycleField:
    """A configured code field and its evidence-limited classification."""

    column: str
    evidence_class: str
    assertion_level: str
    publish_values: bool = True


@dataclass(frozen=True)
class UsefulCombination:
    """A bounded combination of low-cardinality configured code fields."""

    label: str
    columns: tuple[str, ...]
    limit: int = 20


@dataclass(frozen=True)
class LifecycleSource:
    """One local CSV export and the evidence fields that may be inventoried."""

    name: str
    path: Path
    fields: tuple[LifecycleField, ...]
    combinations: tuple[UsefulCombination, ...] = ()


@dataclass(frozen=True)
class FieldProfile:
    """Aggregate code counts for one field; values exist only for approved codes."""

    blank_rows: int
    nonblank_rows: int
    distinct_values: int
    value_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class CombinationProfile:
    """The top configured combinations and the number not shown."""

    definition: UsefulCombination
    rows: tuple[tuple[str, ...], ...]
    omitted_rows: int


@dataclass(frozen=True)
class LifecycleSourceResult:
    """Aggregate lifecycle evidence for one source."""

    definition: LifecycleSource
    row_count: int
    fields: dict[str, FieldProfile]
    combinations: tuple[CombinationProfile, ...]


@dataclass(frozen=True)
class LifecycleProfile:
    """Aggregate-only lifecycle discovery output."""

    sources: tuple[LifecycleSourceResult, ...]


MATRIX_COLUMNS = (
    "source",
    "field",
    "code",
    "observed_count",
    "evidence_class",
    "assertion_level",
    "draft_lifecycle_name",
    "countability_effect",
    "review_note",
)


def build_lifecycle_profile(sources: Iterable[LifecycleSource]) -> LifecycleProfile:
    """Inventory configured fields, retaining only aggregate approved code counts."""
    return LifecycleProfile(
        sources=tuple(_profile_source(source) for source in sources)
    )


def _profile_source(source: LifecycleSource) -> LifecycleSourceResult:
    if not source.path.is_file():
        raise LifecycleDiscoveryError(
            f"Configured source does not exist: {source.path}"
        )
    fields_by_column = {field.column: field for field in source.fields}
    if len(fields_by_column) != len(source.fields):
        raise LifecycleDiscoveryError(
            f"Source {source.name!r} configures a field twice."
        )
    configured_columns = tuple(
        dict.fromkeys(
            [
                *(field.column for field in source.fields),
                *(column for item in source.combinations for column in item.columns),
            ]
        )
    )
    if any(not item.columns or item.limit < 1 for item in source.combinations):
        raise LifecycleDiscoveryError(
            "Useful combinations need columns and a positive limit."
        )

    with source.path.open(encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        headers = tuple(reader.fieldnames or ())
        missing = [column for column in configured_columns if column not in headers]
        if missing:
            raise LifecycleDiscoveryError(
                f"Source {source.name!r} is missing configured columns: "
                + ", ".join(missing)
            )
        counts = {column: Counter() for column in fields_by_column}
        blanks = {column: 0 for column in fields_by_column}
        combinations = [Counter() for _ in source.combinations]
        row_count = 0
        for row in reader:
            row_count += 1
            values = {
                column: (row.get(column) or "").strip() for column in configured_columns
            }
            for column in fields_by_column:
                if values[column]:
                    counts[column][values[column]] += 1
                else:
                    blanks[column] += 1
            for index, definition in enumerate(source.combinations):
                combination = tuple(values[column] for column in definition.columns)
                if all(combination):
                    combinations[index][combination] += 1

    profiles = {
        column: FieldProfile(
            blank_rows=blanks[column],
            nonblank_rows=row_count - blanks[column],
            distinct_values=len(counts[column]),
            value_counts=(
                tuple(_ordered_counts(counts[column]))
                if fields_by_column[column].publish_values
                else ()
            ),
        )
        for column in fields_by_column
    }
    combination_profiles = []
    for definition, counts_for_combination in zip(
        source.combinations, combinations, strict=True
    ):
        ordered = _ordered_counts(counts_for_combination)
        shown = ordered[: definition.limit]
        combination_profiles.append(
            CombinationProfile(
                definition=definition,
                rows=tuple((*values, count) for values, count in shown),
                omitted_rows=len(ordered) - len(shown),
            )
        )
    return LifecycleSourceResult(
        definition=source,
        row_count=row_count,
        fields=profiles,
        combinations=tuple(combination_profiles),
    )


def _ordered_counts(counts: Counter) -> list[tuple]:
    """Sort counts deterministically, putting more frequent values first."""
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def matrix_rows(profile: LifecycleProfile) -> list[dict[str, str]]:
    """Return reviewer-facing rows, excluding individual metadata identifiers."""
    rows = []
    for source in profile.sources:
        for field in source.definition.fields:
            statistics = source.fields[field.column]
            if field.publish_values:
                rows.extend(
                    {
                        "source": source.definition.name,
                        "field": field.column,
                        "code": value,
                        "observed_count": str(count),
                        "evidence_class": field.evidence_class,
                        "assertion_level": field.assertion_level,
                        "draft_lifecycle_name": "unknown",
                        "countability_effect": "unresolved",
                        "review_note": "",
                    }
                    for value, count in statistics.value_counts
                )
            else:
                rows.append(
                    {
                        "source": source.definition.name,
                        "field": field.column,
                        "code": "aggregate only",
                        "observed_count": str(statistics.distinct_values),
                        "evidence_class": field.evidence_class,
                        "assertion_level": field.assertion_level,
                        "draft_lifecycle_name": "unknown",
                        "countability_effect": "unresolved",
                        "review_note": "Individual values are intentionally not published.",
                    }
                )
    return rows


def write_evidence_matrix(profile: LifecycleProfile, output_path: Path) -> None:
    """Write the matrix while retaining human-reviewed meaning and note columns."""
    existing = _read_existing_mappings(output_path)
    rows = matrix_rows(profile)
    for row in rows:
        reviewed = existing.get(_matrix_key(row))
        if reviewed:
            for column in (
                "draft_lifecycle_name",
                "countability_effect",
                "review_note",
            ):
                row[column] = reviewed[column]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=MATRIX_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _read_existing_mappings(path: Path) -> dict[tuple[str, str, str], dict[str, str]]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        if not set(MATRIX_COLUMNS).issubset(reader.fieldnames or ()):
            return {}
        return {_matrix_key(row): row for row in reader}


def _matrix_key(row: dict[str, str]) -> tuple[str, str, str]:
    return row["source"], row["field"], row["code"]


def render_markdown(profile: LifecycleProfile) -> str:
    """Render aggregate evidence and uncertainty without member-level values."""
    lines = [
        "# Membership lifecycle evidence taxonomy",
        "",
        "This aggregate-only discovery records what the four local exports can "
        "support. It does not establish lifecycle rules or operational counting rules.",
        "",
        "## Evidence interpretation",
        "",
        "- Direct facts are source-field observations, such as a populated status "
        "or payment field. They do not by themselves explain why a state exists.",
        "- State observations describe a snapshot or recorded state; they are not "
        "proof of a transition.",
        "- Possible inferences are unvalidated interpretations of event-candidate "
        "codes. They must be reviewed before use.",
        "- Payment activity never automatically creates a countable-status transition. "
        "Every countability effect remains unresolved until a later rule is validated.",
        "",
        "The unvalidated draft vocabulary is `joined`, `reinstated`, `resigned`, "
        "`expelled`, `transferred`, `corrected`, and `other observed`. These are "
        "possible inferences, not rules.",
        "",
    ]
    for source in profile.sources:
        lines.extend(
            [
                f"## {source.definition.name}",
                "",
                f"- Local input path: `{source.definition.path.as_posix()}`",
                f"- Rows: {source.row_count}",
                "",
                "### Configured field inventory",
                "",
                "| Field | Evidence class | Assertion level | Blank rows | Nonblank rows | Distinct values |",
                "| --- | --- | --- | ---: | ---: | ---: |",
            ]
        )
        for field in source.definition.fields:
            stats = source.fields[field.column]
            lines.append(
                f"| `{field.column}` | {field.evidence_class} | {field.assertion_level} | "
                f"{stats.blank_rows} | {stats.nonblank_rows} | {stats.distinct_values} |"
            )
        for combination in source.combinations:
            lines.extend(
                [
                    "",
                    f"### {combination.definition.label}",
                    "",
                    "Only nonblank configured code combinations are shown. Values are "
                    "sorted by frequency and then alphabetically for repeatable output.",
                    "",
                    "| " + " | ".join(combination.definition.columns) + " | Rows |",
                    "| "
                    + " | ".join("---" for _ in combination.definition.columns)
                    + " | ---: |",
                ]
            )
            lines.extend(
                "| " + " | ".join(row[:-1]) + f" | {row[-1]} |"
                for row in combination.rows
            )
            if combination.omitted_rows:
                lines.append(
                    f"\n{combination.omitted_rows} lower-frequency combinations are omitted."
                )
        lines.append("")
    lines.extend(
        [
            "## Privacy and retention boundary",
            "",
            "Names, member IDs, company IDs, notes, descriptions, and transaction "
            "identifiers are never rendered. Transaction identifiers are reported only "
            "as aggregate cardinality. The committed matrix records approved lower-"
            "cardinality codes and reviewer decisions; raw exports remain local.",
            "",
        ]
    )
    return "\n".join(lines)
