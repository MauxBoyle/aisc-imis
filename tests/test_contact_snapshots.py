"""Tests for combining CSContactBasic snapshots."""

import csv
from pathlib import Path

import pytest

from aisc_imis.contact_snapshots import (
    combine_contact_snapshots,
    find_snapshot_files,
    split_contact_snapshots,
)


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_combines_exact_and_compatible_rows_but_preserves_conflicts(tmp_path):
    first = tmp_path / "Full_CSContactBasic_first.csv"
    second = tmp_path / "Changed_CSContactBasic_second.csv"
    output = tmp_path / "combined.csv"
    _write_csv(
        first,
        ["iMIS Id", "Last Updated", "Company", "Email"],
        [
            {
                "iMIS Id": "1",
                "Last Updated": "2025-01-01",
                "Company": "Acme",
                "Email": "",
            },
            {
                "iMIS Id": "2",
                "Last Updated": "2025-01-01",
                "Company": "Beta",
                "Email": "old@example.com",
            },
        ],
    )
    _write_csv(
        second,
        ["iMIS Id", "Last Updated", "Company", "Email", "Website", "isMax"],
        [
            {
                "iMIS Id": "1",
                "Last Updated": "2025-01-01",
                "Company": "Acme",
                "Email": "a@example.com",
                "Website": "acme.test",
                "isMax": "1",
            },
            {
                "iMIS Id": "1",
                "Last Updated": "2025-02-01",
                "Company": "Acme",
                "Email": "a@example.com",
                "Website": "acme.test",
                "isMax": "1",
            },
            {
                "iMIS Id": "2",
                "Last Updated": "2025-01-01",
                "Company": "Beta",
                "Email": "new@example.com",
                "Website": "",
                "isMax": "1",
            },
        ],
    )

    stats = combine_contact_snapshots([first, second], output)

    with output.open(newline="") as output_file:
        reader = csv.DictReader(output_file)
        rows = list(reader)
    assert reader.fieldnames == [
        "iMIS Id",
        "Last Updated",
        "Company",
        "Email",
        "Website",
    ]
    assert stats.input_rows == 5
    assert stats.output_rows == 4
    assert rows[0] == {
        "iMIS Id": "1",
        "Last Updated": "2025-01-01",
        "Company": "Acme",
        "Email": "a@example.com",
        "Website": "acme.test",
    }
    assert [row["Email"] for row in rows if row["iMIS Id"] == "2"] == [
        "new@example.com",
        "old@example.com",
    ]


def test_exact_duplicates_and_missing_last_updated_are_handled(tmp_path):
    source = tmp_path / "Full_CSContactBasic_MB.csv"
    output = tmp_path / "combined.csv"
    rows = [
        {"iMIS Id": "1", "Company": "Acme"},
        {"iMIS Id": "1", "Company": "Acme"},
    ]
    _write_csv(source, ["iMIS Id", "Company"], rows)

    # Another file supplies the required column, while this source receives blanks.
    dated = tmp_path / "Full_CSContactBasic_dated.csv"
    _write_csv(
        dated,
        ["iMIS Id", "Last Updated", "Company"],
        [{"iMIS Id": "2", "Last Updated": "2025-01-01", "Company": "Beta"}],
    )

    stats = combine_contact_snapshots([source, dated], output)

    assert stats.input_rows == 3
    assert stats.exact_unique_rows == 2
    assert stats.output_rows == 2


def test_finds_matching_files_case_insensitively(tmp_path):
    matching = tmp_path / "COMBINED_CSCONTACTBASIC.csv"
    matching.write_text("iMIS Id,Last Updated\n", encoding="utf-8")
    excluded = tmp_path / "Full_CSContactBasic_MB_1.csv"
    excluded.write_text("iMIS Id,Company\n", encoding="utf-8")
    (tmp_path / "other.csv").write_text("x\n", encoding="utf-8")

    assert find_snapshot_files(tmp_path) == [matching]


def test_standardizes_easy_text_conflicts_and_keeps_preferred_values(tmp_path):
    first = tmp_path / "Full_CSContactBasic_first.csv"
    second = tmp_path / "Changed_CSContactBasic_second.csv"
    output = tmp_path / "combined.csv"
    fields = ["iMIS Id", "Last Updated", "Company", "Country", "Full Address"]
    _write_csv(
        first,
        fields,
        [
            {
                "iMIS Id": "1",
                "Last Updated": "2025-01-01",
                "Company": "Barry Isett and Associates",
                "Country": "CZECH REPUBLIC",
                "Full Address": "1 Main Street\r\nPrague",
            }
        ],
    )
    _write_csv(
        second,
        fields,
        [
            {
                "iMIS Id": "1",
                "Last Updated": "2025-01-01",
                "Company": "Barry Isett & Associates, Inc.",
                "Country": "Czechia",
                "Full Address": "1 Main Street\r\r\nPrague",
            }
        ],
    )

    stats = combine_contact_snapshots([first, second], output)

    with output.open(newline="") as output_file:
        rows = list(csv.DictReader(output_file))
    assert stats.output_rows == 1
    assert rows == [
        {
            "iMIS Id": "1",
            "Last Updated": "2025-01-01",
            "Company": "Barry Isett & Associates, Inc.",
            "Country": "Czechia",
            "Full Address": "1 Main Street\nPrague",
        }
    ]


def test_uses_parent_member_type_to_resolve_a_branch_type(tmp_path):
    source = tmp_path / "Full_CSContactBasic.csv"
    output = tmp_path / "combined.csv"
    fields = [
        "iMIS Id",
        "Last Updated",
        "Major Key",
        "Member Type",
        "Company Member Type",
    ]
    _write_csv(
        source,
        fields,
        [
            {
                "iMIS Id": "100",
                "Last Updated": "2025-01-01 10:00:00 AM",
                "Major Key": "100",
                "Member Type": "PROF",
                "Company Member Type": "",
            },
            {
                "iMIS Id": "200",
                "Last Updated": "2025-01-02 10:00:00 AM",
                "Major Key": "100",
                "Member Type": "PROFD",
                "Company Member Type": "PROF",
            },
            {
                "iMIS Id": "200",
                "Last Updated": "2025-01-02 10:00:00 AM",
                "Major Key": "100",
                "Member Type": "PROFD",
                "Company Member Type": "PROFB",
            },
        ],
    )

    stats = combine_contact_snapshots([source], output)

    with output.open(newline="") as output_file:
        rows = list(csv.DictReader(output_file))
    assert stats.output_rows == 2
    assert rows[1]["Company Member Type"] == "PROFB"


def test_uses_is_member_to_resolve_former_professional_and_affiliate(tmp_path):
    source = tmp_path / "Full_CSContactBasic.csv"
    output = tmp_path / "combined.csv"
    fields = ["iMIS Id", "Last Updated", "Company Member Type", "Is Member"]
    _write_csv(
        source,
        fields,
        [
            {
                "iMIS Id": "1",
                "Last Updated": "2025-01-01 10:00:00 AM",
                "Company Member Type": "FPROF",
                "Is Member": "False",
            },
            {
                "iMIS Id": "1",
                "Last Updated": "2025-01-01 10:00:00 AM",
                "Company Member Type": "PROF",
                "Is Member": "False",
            },
            {
                "iMIS Id": "2",
                "Last Updated": "2025-01-01 10:00:00 AM",
                "Company Member Type": "AFF",
                "Is Member": "True",
            },
            {
                "iMIS Id": "2",
                "Last Updated": "2025-01-01 10:00:00 AM",
                "Company Member Type": "FAFF",
                "Is Member": "True",
            },
        ],
    )

    stats = combine_contact_snapshots([source], output)

    with output.open(newline="") as output_file:
        rows = list(csv.DictReader(output_file))
    assert stats.output_rows == 2
    assert [row["Company Member Type"] for row in rows] == ["FPROF", "AFF"]


def test_keeps_professional_branch_and_dependent_records_as_members(tmp_path):
    source = tmp_path / "Full_CSContactBasic.csv"
    output = tmp_path / "combined.csv"
    fields = ["iMIS Id", "Last Updated", "Member Type", "Is Member"]
    _write_csv(
        source,
        fields,
        [
            {
                "iMIS Id": "1",
                "Last Updated": "2025-01-01 10:00:00 AM",
                "Member Type": "PROFB",
                "Is Member": "False",
            },
            {
                "iMIS Id": "1",
                "Last Updated": "2025-01-01 10:00:00 AM",
                "Member Type": "PROFB",
                "Is Member": "True",
            },
            {
                "iMIS Id": "2",
                "Last Updated": "2025-01-01 10:00:00 AM",
                "Member Type": "PROFD",
                "Is Member": "False",
            },
            {
                "iMIS Id": "2",
                "Last Updated": "2025-01-01 10:00:00 AM",
                "Member Type": "PROFD",
                "Is Member": "True",
            },
        ],
    )

    stats = combine_contact_snapshots([source], output)

    with output.open(newline="") as output_file:
        rows = list(csv.DictReader(output_file))
    assert stats.output_rows == 2
    assert [row["Is Member"] for row in rows] == ["True", "True"]


def test_excludes_user_approved_irresolvable_conflict_pair(tmp_path):
    source = tmp_path / "Full_CSContactBasic.csv"
    output = tmp_path / "combined.csv"
    fields = ["iMIS Id", "Last Updated", "Company"]
    _write_csv(
        source,
        fields,
        [
            {
                "iMIS Id": "3244293",
                "Last Updated": "6/5/2025 10:55:23 AM",
                "Company": "Martin/Martin Inc.",
            },
            {
                "iMIS Id": "3244293",
                "Last Updated": "6/5/2025 10:55:23 AM",
                "Company": "Martin/Martin - Lakewood, Colorado",
            },
            {
                "iMIS Id": "1",
                "Last Updated": "2025-01-01",
                "Company": "Acme",
            },
        ],
    )

    stats = combine_contact_snapshots([source], output)

    with output.open(newline="") as output_file:
        rows = list(csv.DictReader(output_file))
    assert stats.input_rows == 3
    assert stats.output_rows == 1
    assert rows[0]["iMIS Id"] == "1"


def test_uses_member_type_to_resolve_company_member_type(tmp_path):
    source = tmp_path / "Full_CSContactBasic.csv"
    output = tmp_path / "combined.csv"
    fields = ["iMIS Id", "Last Updated", "Member Type", "Company Member Type"]
    _write_csv(
        source,
        fields,
        [
            {
                "iMIS Id": "1",
                "Last Updated": "2025-01-01 10:00:00 AM",
                "Member Type": "ACTD",
                "Company Member Type": "ACT",
            },
            {
                "iMIS Id": "1",
                "Last Updated": "2025-01-01 10:00:00 AM",
                "Member Type": "ACTD",
                "Company Member Type": "PROF",
            },
            {
                "iMIS Id": "2",
                "Last Updated": "2025-01-01 10:00:00 AM",
                "Member Type": "ASSCD",
                "Company Member Type": "ASSOC",
            },
            {
                "iMIS Id": "2",
                "Last Updated": "2025-01-01 10:00:00 AM",
                "Member Type": "ASSCD",
                "Company Member Type": "ASSCB",
            },
        ],
    )

    stats = combine_contact_snapshots([source], output)

    with output.open(newline="") as output_file:
        rows = list(csv.DictReader(output_file))
    assert stats.output_rows == 3
    assert rows[0]["Company Member Type"] == "ACT"
    assert {row["Company Member Type"] for row in rows[1:]} == {"ASSCB", "ASSOC"}


def test_uses_join_date_to_resolve_2026_member_status(tmp_path):
    source = tmp_path / "Full_CSContactBasic.csv"
    output = tmp_path / "combined.csv"
    fields = ["iMIS Id", "Last Updated", "Join Date", "Member Status"]
    _write_csv(
        source,
        fields,
        [
            {
                "iMIS Id": "1",
                "Last Updated": "1/20/2026 10:00:00 AM",
                "Join Date": "1/1/2026",
                "Member Status": "New",
            },
            {
                "iMIS Id": "1",
                "Last Updated": "1/20/2026 10:00:00 AM",
                "Join Date": "1/1/2026",
                "Member Status": "Renewed",
            },
            {
                "iMIS Id": "2",
                "Last Updated": "6/1/2026 10:00:00 AM",
                "Join Date": "1/1/2010",
                "Member Status": "New",
            },
            {
                "iMIS Id": "2",
                "Last Updated": "6/1/2026 10:00:00 AM",
                "Join Date": "1/1/2010",
                "Member Status": "Renewed",
            },
        ],
    )

    stats = combine_contact_snapshots([source], output)

    with output.open(newline="") as output_file:
        rows = list(csv.DictReader(output_file))
    assert stats.output_rows == 2
    assert [row["Member Status"] for row in rows] == ["New", "Renewed"]


def test_splits_current_and_historical_rows_by_latest_timestamp(tmp_path):
    source = tmp_path / "combined.csv"
    current = tmp_path / "current.csv"
    history = tmp_path / "history.csv"
    fields = ["iMIS Id", "Last Updated", "Company"]
    _write_csv(
        source,
        fields,
        [
            {
                "iMIS Id": "1",
                "Last Updated": "2/1/2026 9:00:00 AM",
                "Company": "New",
            },
            {
                "iMIS Id": "2",
                "Last Updated": "1/5/2026 1:00:00 PM",
                "Company": "Only",
            },
            {
                "iMIS Id": "1",
                "Last Updated": "12/1/2025 9:00:00 AM",
                "Company": "Old",
            },
        ],
    )

    stats = split_contact_snapshots(source, current, history)

    with current.open(newline="") as current_file:
        current_rows = list(csv.DictReader(current_file))
    with history.open(newline="") as history_file:
        history_rows = list(csv.DictReader(history_file))
    assert stats.input_rows == 3
    assert stats.member_ids == 2
    assert stats.current_rows == 2
    assert stats.history_rows == 1
    assert [(row["iMIS Id"], row["Company"]) for row in current_rows] == [
        ("1", "New"),
        ("2", "Only"),
    ]
    assert history_rows == [
        {
            "iMIS Id": "1",
            "Last Updated": "12/1/2025 9:00:00 AM",
            "Company": "Old",
        }
    ]


def test_split_rejects_multiple_rows_at_latest_timestamp(tmp_path):
    source = tmp_path / "combined.csv"
    fields = ["iMIS Id", "Last Updated", "Company"]
    _write_csv(
        source,
        fields,
        [
            {
                "iMIS Id": "1",
                "Last Updated": "2/1/2026 9:00:00 AM",
                "Company": "First",
            },
            {
                "iMIS Id": "1",
                "Last Updated": "2/1/2026 9:00:00 AM",
                "Company": "Second",
            },
        ],
    )

    with pytest.raises(ValueError, match="multiple rows at their newest timestamp"):
        split_contact_snapshots(
            source, tmp_path / "current.csv", tmp_path / "history.csv"
        )
