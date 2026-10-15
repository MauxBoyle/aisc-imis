"""Tests for aggregate-only membership date-semantics discovery."""

import csv
import importlib.util
from datetime import date
from pathlib import Path

import pytest

from aisc_imis.date_discovery import (
    DateDiscoveryError,
    DateField,
    DatePair,
    DateSource,
    build_date_profile,
    render_markdown,
)


def write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def source(path: Path) -> DateSource:
    return DateSource(
        name="Synthetic source",
        path=path,
        fields=(
            DateField("Effective", "Candidate effective date", "Needs validation."),
            DateField("Recorded", "Recorded date", "Needs validation."),
        ),
        pairs=(DatePair("Effective compared with recorded", "Effective", "Recorded"),),
    )


def test_profiles_precision_timezone_invalid_and_implausible_dates(tmp_path):
    path = tmp_path / "dates.csv"
    write_csv(
        path,
        ["Effective", "Recorded", "Member ID"],
        [
            {"Effective": "2026-01-01", "Recorded": "2026-01-02", "Member ID": "1"},
            {
                "Effective": "01/03/2026 1:02 PM",
                "Recorded": "2026-01-03T12:00:00+00:00",
                "Member ID": "2",
            },
            {"Effective": "", "Recorded": "bad date", "Member ID": "3"},
            {"Effective": "3026-01-01", "Recorded": "", "Member ID": "4"},
        ],
    )

    result = build_date_profile([source(path)], reference_date=date(2026, 10, 15))
    effective = result.sources[0].fields["Effective"]
    recorded = result.sources[0].fields["Recorded"]

    assert effective.blank_values == 1
    assert effective.parseable_values == 3
    assert effective.invalid_values == 0
    assert effective.date_only_values == 2
    assert effective.timestamp_values == 1
    assert effective.explicit_timezone_values == 0
    assert effective.implausible_values == 1
    assert recorded.blank_values == 1
    assert recorded.parseable_values == 2
    assert recorded.invalid_values == 1
    assert recorded.date_only_values == 1
    assert recorded.timestamp_values == 1
    assert recorded.explicit_timezone_values == 1


def test_counts_date_pair_orderings_and_unusable_pairs(tmp_path):
    path = tmp_path / "pairs.csv"
    write_csv(
        path,
        ["Effective", "Recorded"],
        [
            {"Effective": "2026-01-01", "Recorded": "2026-01-02"},
            {"Effective": "2026-01-02", "Recorded": "2026-01-02"},
            {"Effective": "2026-01-03", "Recorded": "2026-01-02"},
            {"Effective": "", "Recorded": "2026-01-02"},
            {"Effective": "bad date", "Recorded": "2026-01-02"},
        ],
    )

    pair = build_date_profile([source(path)]).sources[0].pairs[0]

    assert pair.earlier_values == 1
    assert pair.same_values == 1
    assert pair.later_values == 1
    assert pair.missing_pair_values == 1
    assert pair.invalid_pair_values == 1


def test_markdown_contains_aggregates_but_never_source_values(tmp_path):
    path = tmp_path / "private.csv"
    write_csv(
        path,
        ["Effective", "Recorded", "Member ID"],
        [
            {
                "Effective": "2026-01-01",
                "Recorded": "2026-01-03",
                "Member ID": "9988",
            }
        ],
    )

    markdown = render_markdown(build_date_profile([source(path)]))

    assert "9988" not in markdown
    assert "2026-01-01" not in markdown
    assert "Earlier (left < right)" in markdown
    assert "Candidate effective date" in markdown


def test_fails_safely_for_missing_files_or_configured_columns(tmp_path):
    with pytest.raises(DateDiscoveryError, match="does not exist"):
        build_date_profile([source(tmp_path / "missing.csv")])

    path = tmp_path / "incomplete.csv"
    write_csv(path, ["Effective"], [{"Effective": "2026-01-01"}])
    with pytest.raises(DateDiscoveryError, match="missing configured columns"):
        build_date_profile([source(path)])


def test_generator_configures_all_date_fields_in_four_known_schemas():
    script_path = (
        Path(__file__).parents[1] / "scripts" / "generate_membership_date_semantics.py"
    )
    spec = importlib.util.spec_from_file_location("date_semantics_generator", script_path)
    assert spec is not None and spec.loader is not None
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)

    configured_fields = {
        source.name: {field.column for field in source.fields}
        for source in generator.default_sources()
    }

    assert configured_fields == {
        "Current records": {"Date Added", "Join Date", "Last Updated"},
        "CSContactBasic history": {"Date Added", "Join Date", "Last Updated"},
        "Membership changes": {
            "ChangeUpdate",
            "ChangeCreated",
            "ChangeEffective",
            "Thru Date",
            "ContactUpdateLast",
            "Member Status Date",
            "Paid Through",
            "ContactUpdated",
        },
        "Activity history": {"Effective Date", "Transaction Date"},
    }
