"""Profile configured CSV date fields using aggregate-only evidence."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


class DateDiscoveryError(ValueError):
    """Raised when a configured date source cannot be profiled safely."""


@dataclass(frozen=True)
class DateField:
    """A date column plus its documented, evidence-limited interpretation."""

    column: str
    classification: str
    note: str


@dataclass(frozen=True)
class DatePair:
    """Two date columns to compare, with the left column compared to the right."""

    label: str
    left_column: str
    right_column: str


@dataclass(frozen=True)
class DateSource:
    """One CSV input and its configured date fields and date-pair checks."""

    name: str
    path: Path
    fields: tuple[DateField, ...]
    pairs: tuple[DatePair, ...] = ()


@dataclass(frozen=True)
class DateFieldStats:
    """Aggregate completeness, validity, precision, timezone, and range counts."""

    blank_values: int
    parseable_values: int
    invalid_values: int
    date_only_values: int
    timestamp_values: int
    explicit_timezone_values: int
    implausible_values: int


@dataclass(frozen=True)
class DatePairStats:
    """Aggregate relationship counts for one configured left/right date pair."""

    definition: DatePair
    earlier_values: int
    same_values: int
    later_values: int
    missing_pair_values: int
    invalid_pair_values: int


@dataclass(frozen=True)
class DateSourceResult:
    """Aggregate profile for one source, with no source cell values retained."""

    definition: DateSource
    row_count: int
    fields: dict[str, DateFieldStats]
    pairs: tuple[DatePairStats, ...]


@dataclass(frozen=True)
class DateProfile:
    """Aggregate-only date discovery output."""

    sources: tuple[DateSourceResult, ...]
    reference_date: date


def build_date_profile(
    sources: Iterable[DateSource], *, reference_date: date | None = None
) -> DateProfile:
    """Profile sources without retaining member-level rows or date strings."""
    effective_reference_date = reference_date or date.today()
    return DateProfile(
        sources=tuple(
            _profile_source(source, effective_reference_date) for source in sources
        ),
        reference_date=effective_reference_date,
    )


def _profile_source(source: DateSource, reference_date: date) -> DateSourceResult:
    if not source.path.is_file():
        raise DateDiscoveryError(f"Configured source does not exist: {source.path}")

    fields_by_column = {field.column: field for field in source.fields}
    if len(fields_by_column) != len(source.fields):
        raise DateDiscoveryError(f"Source {source.name!r} configures a date column twice.")
    configured_columns = tuple(
        dict.fromkeys(
            [
                *(field.column for field in source.fields),
                *(pair.left_column for pair in source.pairs),
                *(pair.right_column for pair in source.pairs),
            ]
        )
    )

    with source.path.open(encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        headers = tuple(reader.fieldnames or ())
        missing = [column for column in configured_columns if column not in headers]
        if missing:
            raise DateDiscoveryError(
                f"Source {source.name!r} is missing configured columns: "
                + ", ".join(missing)
            )

        counts = {
            column: {
                "blank": 0,
                "parseable": 0,
                "invalid": 0,
                "date_only": 0,
                "timestamp": 0,
                "timezone": 0,
                "implausible": 0,
            }
            for column in fields_by_column
        }
        pair_counts = [
            {"earlier": 0, "same": 0, "later": 0, "missing": 0, "invalid": 0}
            for _ in source.pairs
        ]
        row_count = 0

        for row in reader:
            row_count += 1
            parsed_values: dict[str, date | None] = {}
            value_states: dict[str, str] = {}
            for column in configured_columns:
                raw_value = (row.get(column) or "").strip()
                if not raw_value:
                    value_states[column] = "blank"
                    parsed_values[column] = None
                    if column in counts:
                        counts[column]["blank"] += 1
                    continue
                parsed = _parse_date(raw_value)
                if parsed is None:
                    value_states[column] = "invalid"
                    parsed_values[column] = None
                    if column in counts:
                        counts[column]["invalid"] += 1
                    continue
                value_states[column] = "parsed"
                parsed_values[column] = parsed[0]
                if column in counts:
                    _count_parsed_value(counts[column], parsed, reference_date)

            for index, pair in enumerate(source.pairs):
                left_state = value_states[pair.left_column]
                right_state = value_states[pair.right_column]
                if left_state == "blank" or right_state == "blank":
                    pair_counts[index]["missing"] += 1
                elif left_state == "invalid" or right_state == "invalid":
                    pair_counts[index]["invalid"] += 1
                elif parsed_values[pair.left_column] < parsed_values[pair.right_column]:
                    pair_counts[index]["earlier"] += 1
                elif parsed_values[pair.left_column] > parsed_values[pair.right_column]:
                    pair_counts[index]["later"] += 1
                else:
                    pair_counts[index]["same"] += 1

    return DateSourceResult(
        definition=source,
        row_count=row_count,
        fields={
            column: DateFieldStats(
                blank_values=count["blank"],
                parseable_values=count["parseable"],
                invalid_values=count["invalid"],
                date_only_values=count["date_only"],
                timestamp_values=count["timestamp"],
                explicit_timezone_values=count["timezone"],
                implausible_values=count["implausible"],
            )
            for column, count in counts.items()
        },
        pairs=tuple(
            DatePairStats(
                definition=pair,
                earlier_values=count["earlier"],
                same_values=count["same"],
                later_values=count["later"],
                missing_pair_values=count["missing"],
                invalid_pair_values=count["invalid"],
            )
            for pair, count in zip(source.pairs, pair_counts, strict=True)
        ),
    )


def _count_parsed_value(
    counts: dict[str, int], parsed: tuple[date, bool, bool], reference_date: date
) -> None:
    parsed_date, is_timestamp, has_explicit_timezone = parsed
    counts["parseable"] += 1
    counts["timestamp" if is_timestamp else "date_only"] += 1
    if has_explicit_timezone:
        counts["timezone"] += 1
    if parsed_date.year < 1900 or parsed_date > reference_date:
        counts["implausible"] += 1


def _parse_date(value: str) -> tuple[date, bool, bool] | None:
    """Parse known export formats while preserving only date-level evidence."""
    for date_format in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, date_format).date(), False, False
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.date(), True, parsed.tzinfo is not None
    except ValueError:
        pass
    for timestamp_format in (
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %I:%M %p",
    ):
        try:
            return datetime.strptime(value, timestamp_format).date(), True, False
        except ValueError:
            continue
    return None


def render_markdown(profile: DateProfile) -> str:
    """Render aggregate findings without including any source cell values."""
    timestamp_values = sum(
        field.timestamp_values
        for source in profile.sources
        for field in source.fields.values()
    )
    explicit_timezone_values = sum(
        field.explicit_timezone_values
        for source in profile.sources
        for field in source.fields.values()
    )
    lines = [
        "# Membership date semantics",
        "",
        "This report contains aggregate evidence only. It never retains or publishes "
        "member IDs, names, or source date values.",
        "",
        "## Scope and guardrails",
        "",
        "Field names alone do not prove business meaning. The classifications below "
        "are working descriptions or explicit open questions, not data-model facts.",
        "",
        "Date-only values remain dates: this discovery does not invent a time of day. "
        "Timezone-free timestamps remain timezone-free; no timezone is assumed or "
        "converted. The explicit-timezone count reports only source values that carry "
        "an offset or `Z` marker.",
        "",
        "Configured pair tables provide aggregate evidence of missing pairs and "
        "left-after-right (out-of-order) pairs; they do not establish business meaning.",
        "",
        f"This run observed {timestamp_values} timestamp values, including "
        f"{explicit_timezone_values} with an explicit timezone marker.",
        "",
        f"Dates before 1900 or after {profile.reference_date.isoformat()} are counted as implausible.",
        "",
    ]
    for result in profile.sources:
        lines.extend(
            [
                f"## {result.definition.name}",
                "",
                f"- Local input path: `{result.definition.path.as_posix()}`",
                f"- Rows: {result.row_count}",
                "",
                "### Field meanings to validate",
                "",
                "| Field | Classification / open question |",
                "| --- | --- |",
            ]
        )
        lines.extend(
            f"| `{field.column}` | {field.classification}. {field.note} |"
            for field in result.definition.fields
        )
        lines.extend(
            [
                "",
                "### Field profile",
                "",
                "| Field | Blank | Parseable | Invalid | Date-only | Timestamp | Explicit timezone | Implausible |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for column, stats in result.fields.items():
            lines.append(
                f"| `{column}` | {stats.blank_values} | {stats.parseable_values} | "
                f"{stats.invalid_values} | {stats.date_only_values} | "
                f"{stats.timestamp_values} | {stats.explicit_timezone_values} | "
                f"{stats.implausible_values} |"
            )
        if result.pairs:
            lines.extend(
                [
                    "",
                    "### Configured pair ordering",
                    "",
                    "The left field is compared with the right field at date precision. "
                    "A missing pair has at least one blank value; an invalid pair has "
                    "no blanks but at least one unparseable value.",
                    "",
                    "| Pair | Earlier (left < right) | Same | Later (left > right) | Missing pair | Invalid pair |",
                    "| --- | ---: | ---: | ---: | ---: | ---: |",
                ]
            )
            lines.extend(
                f"| {pair.definition.label} | {pair.earlier_values} | "
                f"{pair.same_values} | {pair.later_values} | "
                f"{pair.missing_pair_values} | {pair.invalid_pair_values} |"
                for pair in result.pairs
            )
        lines.append("")
    lines.extend(
        [
            "## Recommended date roles",
            "",
            "Use a validated, source-supported effective date only to order effective "
            "events. Preserve recorded, created, transaction, and update dates as "
            "separate provenance. Supply snapshot observation time and reporting cutoff "
            "as independent report inputs; neither is a substitute for a source date.",
            "",
            "## Unresolved meanings",
            "",
            "- Contact dates and membership dates may describe different entities and "
            "must not be treated as interchangeable without validation.",
            "- Payment and through dates may represent entitlement, billing, or another "
            "business rule; their effective-date meaning remains open.",
            "- The reviewed exports do not provide a per-row snapshot-capture timestamp. "
            "A file-level observation time, if known, must be supplied separately.",
            "",
            "## Retention boundary",
            "",
            "The CSV exports remain ignored local operational data in `data/raw/` and "
            "`data/processed/`. This committed document contains only aggregate evidence "
            "and should be regenerated from authorized local exports when inputs change.",
            "",
        ]
    )
    return "\n".join(lines)
