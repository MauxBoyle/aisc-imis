"""Tests for privacy-safe membership-source inventory generation."""

import csv
from datetime import date
from pathlib import Path

import pytest

from aisc_imis.source_inventory import (
    SourceDefinition,
    SourceInventoryError,
    build_inventory,
    render_markdown,
)


def write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def source(
    path: Path, *, key: tuple[str, ...], dates: tuple[str, ...]
) -> SourceDefinition:
    return SourceDefinition(
        name="Synthetic source",
        path=path,
        source_type="synthetic",
        candidate_key=key,
        date_columns=dates,
        required_columns=key + dates,
        extraction_note="Synthetic test input.",
    )


def test_collects_schema_null_patterns_key_and_date_aggregates(tmp_path):
    path = tmp_path / "current.csv"
    write_csv(
        path,
        ["iMIS Id", "Last Updated", "Email"],
        [
            {
                "iMIS Id": "1",
                "Last Updated": "2026-01-01",
                "Email": "alice@example.test",
            },
            {"iMIS Id": "1", "Last Updated": "not a date", "Email": ""},
            {"iMIS Id": "", "Last Updated": "3026-01-01", "Email": "bob@example.test"},
        ],
    )

    result = build_inventory(
        [source(path, key=("iMIS Id",), dates=("Last Updated",))],
        reference_date=date(2026, 10, 15),
    ).sources[0]

    assert result.headers == ("iMIS Id", "Last Updated", "Email")
    assert result.row_count == 3
    assert result.null_counts == {"iMIS Id": 1, "Last Updated": 0, "Email": 1}
    assert any(
        pattern.columns == ("iMIS Id",) and pattern.row_count == 1
        for pattern in result.null_patterns
    )
    assert result.candidate_key.complete_rows == 2
    assert result.candidate_key.distinct_complete_keys == 1
    assert result.candidate_key.duplicate_complete_rows == 1
    coverage = result.date_coverage["Last Updated"]
    assert coverage.nonblank_values == 3
    assert coverage.parsed_values == 2
    assert coverage.unparseable_values == 1
    assert coverage.earliest == "2026-01-01"
    assert coverage.latest == "3026-01-01"
    assert coverage.implausible_values == 1


@pytest.mark.parametrize(
    ("filename", "key", "dates"),
    [
        ("current.csv", ("iMIS Id",), ("Last Updated",)),
        ("history.csv", ("iMIS Id", "Last Updated"), ("Last Updated",)),
        ("changes.csv", ("ChangeID", "Ordinal"), ("ChangeEffective",)),
        ("activity.csv", ("iMIS Id", "Sequence"), ("Effective Date",)),
    ],
)
def test_supports_each_membership_source_key_role(tmp_path, filename, key, dates):
    headers = list(dict.fromkeys([*key, *dates]))
    path = tmp_path / filename
    write_csv(path, headers, [dict.fromkeys(headers, "1")])

    result = build_inventory([source(path, key=key, dates=dates)]).sources[0]

    assert result.candidate_key.columns == key
    assert result.candidate_key.complete_rows == 1


def test_fails_safely_for_missing_source_or_required_column(tmp_path):
    missing = source(tmp_path / "absent.csv", key=("iMIS Id",), dates=("Last Updated",))
    with pytest.raises(SourceInventoryError, match="does not exist"):
        build_inventory([missing])

    incomplete = tmp_path / "incomplete.csv"
    write_csv(incomplete, ["iMIS Id"], [{"iMIS Id": "1"}])
    with pytest.raises(SourceInventoryError, match="missing required columns"):
        build_inventory([source(incomplete, key=("iMIS Id",), dates=("Last Updated",))])


def test_markdown_contains_aggregate_metadata_not_member_rows(tmp_path):
    path = tmp_path / "current.csv"
    write_csv(
        path,
        ["iMIS Id", "Last Updated", "Name"],
        [{"iMIS Id": "9988", "Last Updated": "2026-01-01", "Name": "Private Person"}],
    )

    markdown = render_markdown(
        build_inventory([source(path, key=("iMIS Id",), dates=("Last Updated",))])
    )

    assert "Private Person" not in markdown
    assert "9988" not in markdown
    assert "iMIS Id" in markdown
    assert "Rows: 1" in markdown
