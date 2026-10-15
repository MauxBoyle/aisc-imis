"""Tests for aggregate-only membership identifier discovery."""

import csv
from pathlib import Path

from aisc_imis.identifier_discovery import (
    IdentifierComparison,
    IdentifierSource,
    build_identifier_map,
    render_markdown,
)


def write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def test_profiles_completeness_uniqueness_padding_and_normalized_collisions(tmp_path):
    path = tmp_path / "members.csv"
    write_csv(
        path,
        ["iMIS Id", "Major Key", "Company ID"],
        [
            {"iMIS Id": "0012", "Major Key": "12", "Company ID": "ACME"},
            {"iMIS Id": "12", "Major Key": "", "Company ID": "ACME"},
            {"iMIS Id": "", "Major Key": "0012", "Company ID": ""},
            {"iMIS Id": "77", "Major Key": "12", "Company ID": "BETA"},
        ],
    )

    result = build_identifier_map(
        [IdentifierSource("Members", path, ("iMIS Id", "Major Key", "Company ID"))],
        [],
    ).sources[0]

    imis = result.identifiers["iMIS Id"]
    assert imis.nonblank_rows == 3
    assert imis.distinct_values == 3
    assert imis.duplicate_nonblank_rows == 0
    assert imis.leading_zero_values == 1
    assert imis.normalized_collision_groups == 1
    assert imis.values_in_normalized_collision_groups == 2
    assert result.identifiers["Major Key"].blank_rows == 1
    assert result.identifiers["Company ID"].duplicate_nonblank_rows == 1


def test_calculates_exact_intersections_and_denominator_based_match_rates(tmp_path):
    current = tmp_path / "current.csv"
    activity = tmp_path / "activity.csv"
    write_csv(current, ["iMIS Id"], [{"iMIS Id": "1"}, {"iMIS Id": "2"}])
    write_csv(activity, ["iMIS Id"], [{"iMIS Id": "2"}, {"iMIS Id": "3"}])

    identifier_map = build_identifier_map(
        [
            IdentifierSource("Current", current, ("iMIS Id",)),
            IdentifierSource("Activity", activity, ("iMIS Id",)),
        ],
        [
            IdentifierComparison(
                "Current and activity iMIS Id",
                "Current",
                "iMIS Id",
                "Activity",
                "iMIS Id",
                "exact member identifier",
            )
        ],
    )

    comparison = identifier_map.comparisons[0]
    assert comparison.intersection_count == 1
    assert comparison.left_match_rate == 0.5
    assert comparison.right_match_rate == 0.5


def test_markdown_keeps_company_names_and_unsupported_keys_review_only(tmp_path):
    path = tmp_path / "changes.csv"
    write_csv(
        path,
        ["ChangeID", "Ordinal", "Company"],
        [{"ChangeID": "secret-change", "Ordinal": "001", "Company": "Private Co"}],
    )

    markdown = render_markdown(
        build_identifier_map(
            [IdentifierSource("Membership changes", path, ("ChangeID", "Ordinal"))],
            [],
        )
    )

    assert "secret-change" not in markdown
    assert "Private Co" not in markdown
    assert "transaction key only" in markdown
    assert "review-only" in markdown
