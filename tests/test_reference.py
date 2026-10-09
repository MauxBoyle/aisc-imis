"""Tests for iMIS reference-table generation."""

import csv

from aisc_imis.reference import build_reference_tables, write_reference_tables


def _write_export(path):
    rows = [
        {
            "Is Company": "True",
            "Member Type": "FPROF",
            "Previous Member Type": " ACTD ",
            "iMIS Id": "000139",
            "Company": "Nyzen Consulting",
            "Full Address": "13955 Goodwin Ave.\nBurton, OH 44021",
            "Is Member": "False",
            "Major Key": "000139",
            "Status": "A",
        },
        {
            "Is Company": "False",
            "Member Type": "ACT",
            "Previous Member Type": "   ",
            "iMIS Id": "000140",
            "Company": "Example Company",
            "Full Address": "1 Main Street",
            "Is Member": "True",
            "Major Key": "000140",
            "Status": "NB",
        },
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as export_file:
        writer = csv.DictWriter(export_file, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


def test_build_reference_tables_documents_fields_and_shared_lookup(tmp_path):
    export_path = tmp_path / "companies.csv"
    _write_export(export_path)

    tables = build_reference_tables(export_path)

    assert [row["source_column"] for row in tables["variable_dictionary.csv"]] == [
        "Is Company",
        "Member Type",
        "Previous Member Type",
        "iMIS Id",
        "Company",
        "Full Address",
        "Is Member",
        "Major Key",
        "Status",
    ]
    assert tables["variable_dictionary.csv"][1]["reference_table"] == "member_types.csv"
    assert tables["variable_dictionary.csv"][2]["reference_table"] == "member_types.csv"
    assert tables["variable_dictionary.csv"][3]["data_type"] == "text"
    assert tables["variable_dictionary.csv"][7]["data_type"] == "text"
    assert tables["member_types.csv"] == [
        {"code": "ACT", "meaning": "TBD"},
        {"code": "ACTD", "meaning": "TBD"},
        {"code": "FPROF", "meaning": "TBD"},
    ]
    assert tables["statuses.csv"] == [
        {"code": "A", "meaning": "TBD"},
        {"code": "NB", "meaning": "TBD"},
    ]
    assert tables["boolean_values.csv"] == [
        {"value": "False", "meaning": "No"},
        {"value": "True", "meaning": "Yes"},
    ]


def test_write_reference_tables_writes_deterministic_csvs(tmp_path):
    export_path = tmp_path / "companies.csv"
    output_dir = tmp_path / "reference"
    _write_export(export_path)

    written_paths = write_reference_tables(export_path, output_dir)

    assert {path.name for path in written_paths} == {
        "boolean_values.csv",
        "member_types.csv",
        "statuses.csv",
        "variable_dictionary.csv",
    }
    with (output_dir / "member_types.csv").open(newline="") as reference_file:
        assert list(csv.DictReader(reference_file)) == [
            {"code": "ACT", "meaning": "TBD"},
            {"code": "ACTD", "meaning": "TBD"},
            {"code": "FPROF", "meaning": "TBD"},
        ]


def test_write_reference_tables_preserves_existing_curated_meanings(tmp_path):
    export_path = tmp_path / "companies.csv"
    output_dir = tmp_path / "reference"
    _write_export(export_path)
    output_dir.mkdir()
    (output_dir / "member_types.csv").write_text(
        "code,meaning\nACT,Active member\n",
        encoding="utf-8",
    )
    (output_dir / "statuses.csv").write_text(
        "code,meaning\nA,Active record\n",
        encoding="utf-8",
    )

    write_reference_tables(export_path, output_dir)

    with (output_dir / "member_types.csv").open(newline="") as reference_file:
        member_types = {row["code"]: row["meaning"] for row in csv.DictReader(reference_file)}
    with (output_dir / "statuses.csv").open(newline="") as reference_file:
        statuses = {row["code"]: row["meaning"] for row in csv.DictReader(reference_file)}
    assert member_types["ACT"] == "Active member"
    assert member_types["ACTD"] == "TBD"
    assert statuses["A"] == "Active record"
    assert statuses["NB"] == "TBD"
