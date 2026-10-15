"""Profile membership identifiers using aggregate, non-reversible evidence."""

from __future__ import annotations

import csv
import hashlib
import hmac
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


class IdentifierDiscoveryError(ValueError):
    """Raised when an identifier source cannot be safely profiled."""


@dataclass(frozen=True)
class IdentifierSource:
    """A CSV source and the identifier columns to profile."""

    name: str
    path: Path
    identifier_columns: tuple[str, ...]


@dataclass(frozen=True)
class IdentifierComparison:
    """A permitted exact comparison between two configured identifier columns."""

    label: str
    left_source: str
    left_column: str
    right_source: str
    right_column: str
    relationship: str


@dataclass(frozen=True)
class IdentifierStats:
    """Aggregate completeness and normalization findings for one identifier."""

    blank_rows: int
    nonblank_rows: int
    distinct_values: int
    duplicate_nonblank_rows: int
    leading_zero_values: int
    normalized_collision_groups: int
    values_in_normalized_collision_groups: int


@dataclass(frozen=True)
class IdentifierSourceResult:
    """Aggregate identifier results for one source, without per-value state."""

    source: IdentifierSource
    row_count: int
    identifiers: dict[str, IdentifierStats]


@dataclass(frozen=True)
class _ProfiledSource:
    """Short-lived profiling state used only while comparisons are calculated."""

    result: IdentifierSourceResult
    value_digests: dict[str, frozenset[bytes]]


@dataclass(frozen=True)
class ComparisonResult:
    """Aggregate evidence for an explicitly permitted exact comparison."""

    definition: IdentifierComparison
    left_distinct_values: int
    right_distinct_values: int
    intersection_count: int
    left_match_rate: float | None
    right_match_rate: float | None


@dataclass(frozen=True)
class IdentifierMap:
    """Aggregate-only identifier discovery results."""

    sources: tuple[IdentifierSourceResult, ...]
    comparisons: tuple[ComparisonResult, ...]


def build_identifier_map(
    sources: Iterable[IdentifierSource], comparisons: Iterable[IdentifierComparison]
) -> IdentifierMap:
    """Build aggregate identifier evidence without retaining source cell values."""
    digest_key = secrets.token_bytes(32)
    profiled_sources = tuple(_profile_source(source, digest_key) for source in sources)
    by_name = {profiled.result.source.name: profiled for profiled in profiled_sources}
    comparison_results = tuple(
        _compare_identifiers(comparison, by_name) for comparison in comparisons
    )
    return IdentifierMap(
        sources=tuple(profiled.result for profiled in profiled_sources),
        comparisons=comparison_results,
    )


def _profile_source(source: IdentifierSource, digest_key: bytes) -> _ProfiledSource:
    if not source.path.is_file():
        raise IdentifierDiscoveryError(
            f"Configured source does not exist: {source.path}"
        )

    with source.path.open(encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        headers = tuple(reader.fieldnames or ())
        missing = [
            column for column in source.identifier_columns if column not in headers
        ]
        if missing:
            raise IdentifierDiscoveryError(
                f"Source {source.name!r} is missing identifier columns: "
                + ", ".join(missing)
            )

        values = {column: set() for column in source.identifier_columns}
        normalized_values: dict[str, dict[bytes, set[bytes]]] = {
            column: {} for column in source.identifier_columns
        }
        blank_rows = {column: 0 for column in source.identifier_columns}
        leading_zero_values = {column: 0 for column in source.identifier_columns}
        row_count = 0
        for row in reader:
            row_count += 1
            for column in source.identifier_columns:
                value = (row.get(column) or "").strip()
                if not value:
                    blank_rows[column] += 1
                    continue
                value_digest = _digest(value, digest_key)
                values[column].add(value_digest)
                if _has_leading_zero(value):
                    leading_zero_values[column] += 1
                normalized_digest = _digest(_without_numeric_padding(value), digest_key)
                normalized_values[column].setdefault(normalized_digest, set()).add(
                    value_digest
                )

    stats = {}
    for column in source.identifier_columns:
        collisions = [
            variants
            for variants in normalized_values[column].values()
            if len(variants) > 1
        ]
        distinct_values = len(values[column])
        nonblank_rows = row_count - blank_rows[column]
        stats[column] = IdentifierStats(
            blank_rows=blank_rows[column],
            nonblank_rows=nonblank_rows,
            distinct_values=distinct_values,
            duplicate_nonblank_rows=nonblank_rows - distinct_values,
            leading_zero_values=leading_zero_values[column],
            normalized_collision_groups=len(collisions),
            values_in_normalized_collision_groups=sum(
                len(variants) for variants in collisions
            ),
        )
    result = IdentifierSourceResult(
        source=source, row_count=row_count, identifiers=stats
    )
    return _ProfiledSource(
        result=result,
        value_digests={
            column: frozenset(digests) for column, digests in values.items()
        },
    )


def _compare_identifiers(
    comparison: IdentifierComparison, by_name: dict[str, _ProfiledSource]
) -> ComparisonResult:
    try:
        left = by_name[comparison.left_source].value_digests[comparison.left_column]
        right = by_name[comparison.right_source].value_digests[comparison.right_column]
    except KeyError as error:
        raise IdentifierDiscoveryError(
            f"Comparison {comparison.label!r} refers to an unknown source or column."
        ) from error
    intersection_count = len(left & right)
    return ComparisonResult(
        definition=comparison,
        left_distinct_values=len(left),
        right_distinct_values=len(right),
        intersection_count=intersection_count,
        left_match_rate=_match_rate(intersection_count, len(left)),
        right_match_rate=_match_rate(intersection_count, len(right)),
    )


def _digest(value: str, key: bytes) -> bytes:
    """Return a per-run keyed digest that cannot be dictionary-attacked later."""
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()


def _has_leading_zero(value: str) -> bool:
    return value.isdigit() and len(value) > 1 and value.startswith("0")


def _without_numeric_padding(value: str) -> str:
    if not value.isdigit():
        return value
    return value.lstrip("0") or "0"


def _match_rate(matches: int, denominator: int) -> float | None:
    return matches / denominator if denominator else None


def _format_rate(rate: float | None) -> str:
    return f"{rate:.1%}" if rate is not None else "—"


def render_markdown(identifier_map: IdentifierMap) -> str:
    """Render a privacy-safe identifier map that contains no source values."""
    lines = [
        "# Membership identifier map",
        "",
        "This document contains aggregate, non-reversible identifier evidence only. "
        "It does not publish member IDs, company names, or other source values. "
        "Per-value keyed digests exist only during one profiling run and are not "
        "included in the returned results.",
        "",
        "## Joining rules",
        "",
        "Only comparisons listed in **Exact comparison evidence** are supported "
        "exact joins. Identifiers are compared exactly after trimming surrounding "
        "whitespace; leading zeroes are never removed for matching.",
        "",
        "`Major Key` is parent/dependent evidence only when it exactly matches an "
        "`iMIS Id` in the same reviewed export. `Company ID` is not an automatic "
        "join key. Company names and unsupported keys are review-only.",
        "",
        "In the membership-change export, `ChangeID` is the member's iMIS ID. "
        "`Ordinal` identifies the individual change row for that member, so the "
        "composite (`ChangeID`, `Ordinal`) is the candidate row key. Matching "
        "change rows to members across sources should still preserve the source "
        "evidence and remain reviewable.",
        "",
        "## Identifier profiling",
        "",
        "A normalized collision is a group of two or more distinct numeric source "
        "values that would become equal if leading zeroes were removed. It is a "
        "warning, not a basis for a join.",
        "",
    ]
    for result in identifier_map.sources:
        lines.extend(
            [
                f"### {result.source.name}",
                "",
                f"- Local input path: `{result.source.path.as_posix()}`",
                f"- Rows: {result.row_count}",
                "",
                "| Identifier | Blank rows | Nonblank rows | Distinct values | "
                "Duplicate nonblank rows | Values with leading zeroes | "
                "Normalized collision groups | Values in collision groups |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for column, stats in result.identifiers.items():
            lines.append(
                f"| `{column}` | {stats.blank_rows} | {stats.nonblank_rows} | "
                f"{stats.distinct_values} | {stats.duplicate_nonblank_rows} | "
                f"{stats.leading_zero_values} | {stats.normalized_collision_groups} | "
                f"{stats.values_in_normalized_collision_groups} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Exact comparison evidence",
            "",
            "Match rates use each side's distinct nonblank identifier count as its "
            "denominator. A rate of `—` means that side had no nonblank values.",
            "",
            "| Relationship | Left distinct | Right distinct | Exact intersection | "
            "Left match rate | Right match rate |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for result in identifier_map.comparisons:
        definition = result.definition
        label = f"{definition.label} ({definition.relationship})"
        lines.append(
            f"| {label} | {result.left_distinct_values} | "
            f"{result.right_distinct_values} | {result.intersection_count} | "
            f"{_format_rate(result.left_match_rate)} | "
            f"{_format_rate(result.right_match_rate)} |"
        )
    lines.extend(
        [
            "",
            "## Retention boundary",
            "",
            "Raw and processed exports remain ignored local operational files under "
            "`data/raw/` and `data/processed/`. Regenerate this committed aggregate "
            "document only from authorized local exports.",
            "",
        ]
    )
    return "\n".join(lines)
