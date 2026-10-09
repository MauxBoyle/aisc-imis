"""Tests for iMIS duplicate-company candidate reports."""

import csv
import subprocess
import sys
from pathlib import Path

import pytest

from aisc_imis.duplicates import (
    REPORT_COLUMNS,
    find_duplicate_candidates,
    normalize_text,
    write_duplicate_reports,
)


def _write_export(path: Path, rows: list[dict[str, str]], *, bom: bool = False) -> None:
    with path.open("w", encoding="utf-8-sig" if bom else "utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def _row(
    record_id: str,
    company: str,
    address: str,
    *,
    is_company: str = "True",
    member_type: str = "",
    status: str = "",
) -> dict[str, str]:
    return {
        "Is Company": is_company,
        "Member Type": member_type,
        "iMIS Id": record_id,
        "Company": company,
        "Full Address": address,
        "Status": status,
    }


def test_requires_expected_headers(tmp_path):
    input_path = tmp_path / "companies.csv"
    input_path.write_text("iMIS Id,Company\n1,Example\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Missing required CSV columns:.*Is Company"):
        find_duplicate_candidates(input_path)


def test_normalization_zip_extraction_and_company_filtering_accept_bom(tmp_path):
    input_path = tmp_path / "companies.csv"
    _write_export(
        input_path,
        [
            _row("1", "Acme, Inc.", "10 Main Street, Austin TX 78701"),
            _row("2", "Acme Inc", "10 Main St. Austin, TX 78701-1234"),
            _row(
                "3",
                "Acme Inc",
                "10 Main Street, Austin TX 78701",
                is_company="False",
            ),
            _row("4", "Acme Inc", "10 Main Street, Austin TX"),
        ],
        bom=True,
    )

    matches = find_duplicate_candidates(input_path)

    assert normalize_text("  Main St., Suite #4 ") == "main street suite 4"
    assert len(matches) == 1
    assert matches[0]["zip_code"] == "78701"
    assert matches[0]["left_id"] == "1"
    assert matches[0]["right_id"] == "2"


def test_matching_thresholds_and_zip_blocking(tmp_path):
    input_path = tmp_path / "companies.csv"
    _write_export(
        input_path,
        [
            _row("1", "North Star Steel", "100 West Main Avenue, Chicago IL 60601"),
            _row("2", "North Star Steel Inc", "100 W Main Ave., Chicago, IL 60601"),
            _row("3", "North Star Steel Inc", "100 W Main Ave., Chicago, IL 60602"),
            _row("4", "Unrelated Business", "100 W Main Ave., Chicago, IL 60601"),
        ],
    )

    matches = find_duplicate_candidates(input_path, name_threshold=80)

    assert [(match["left_id"], match["right_id"]) for match in matches] == [("1", "2")]
    assert matches[0]["address_score"] >= 90
    assert matches[0]["company_score"] >= 80
    assert find_duplicate_candidates(input_path, address_threshold=101) == []


def test_all_and_act_modes_include_pairs_with_either_act_record(tmp_path):
    input_path = tmp_path / "companies.csv"
    _write_export(
        input_path,
        [
            _row("1", "Acme Steel", "10 Main Street, Austin TX 78701", member_type="ACT"),
            _row("2", "Acme Steel", "10 Main St, Austin TX 78701", member_type="FPROF"),
            _row("3", "Beta Steel", "20 Main Street, Austin TX 78701", member_type="FPROF"),
            _row("4", "Beta Steel", "20 Main St, Austin TX 78701", member_type="FPROF"),
        ],
    )

    assert len(find_duplicate_candidates(input_path, mode="all")) == 2
    act_matches = find_duplicate_candidates(input_path, mode="act")
    assert [(match["left_id"], match["right_id"]) for match in act_matches] == [("1", "2")]
    with pytest.raises(ValueError, match="mode"):
        find_duplicate_candidates(input_path, mode="members")


def test_excludes_company_names_containing_test_case_insensitively(tmp_path):
    input_path = tmp_path / "companies.csv"
    _write_export(
        input_path,
        [
            _row("1", "Real Steel", "10 Main Street, Austin TX 78701"),
            _row("2", "Real Steel Inc", "10 Main St, Austin TX 78701"),
            _row("3", "Test Company", "20 Oak Street, Austin TX 78701"),
            _row("4", "TEST Company Inc", "20 Oak St, Austin TX 78701"),
        ],
    )

    matches = find_duplicate_candidates(input_path, name_threshold=80)

    assert [(match["left_id"], match["right_id"]) for match in matches] == [("1", "2")]


def test_results_are_deterministic_and_reports_have_expected_contents(tmp_path):
    input_path = tmp_path / "companies.csv"
    _write_export(
        input_path,
        [
            _row("20", "Zeta Works", "5 Elm Street, Austin TX 78701", status="A"),
            _row(
                "10",
                "Alpha Works",
                "1 Oak Street, Austin TX 78701",
                member_type="ACT",
                status="A",
            ),
            _row("21", "Zeta Works", "5 Elm St, Austin TX 78701", status="P"),
            _row(
                "11",
                "Alpha Works",
                "1 Oak St, Austin TX 78701",
                member_type="FPROF",
                status="I",
            ),
        ],
    )

    matches = find_duplicate_candidates(input_path)
    assert [(match["left_id"], match["right_id"]) for match in matches] == [
        ("10", "11"),
        ("20", "21"),
    ]

    csv_path, pdf_path = write_duplicate_reports(
        matches,
        tmp_path / "processed",
        mode="all",
        address_threshold=90,
        name_threshold=85,
        timestamp="20261009T101112",
    )
    assert csv_path.name == "imis_duplicate_candidates_all_20261009T101112.csv"
    assert pdf_path.name == "imis_duplicate_candidates_all_20261009T101112.pdf"
    with csv_path.open(newline="") as report_file:
        rows = list(csv.DictReader(report_file))
    assert list(rows[0]) == REPORT_COLUMNS
    assert rows[0]["left_id"] == "10"
    assert rows[0]["left_status"] == "A"
    assert rows[0]["right_status"] == "I"
    assert pdf_path.read_bytes().startswith(b"%PDF")
    assert pdf_path.stat().st_size > 100


def test_cli_defaults_and_options_write_timestamped_pair(tmp_path):
    input_path = tmp_path / "companies.csv"
    output_dir = tmp_path / "reports"
    _write_export(
        input_path,
        [
            _row("1", "Acme Steel", "10 Main Street, Austin TX 78701", member_type="ACT"),
            _row("2", "Acme Steel", "10 Main St, Austin TX 78701"),
        ],
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/find_imis_duplicates.py",
            str(input_path),
            "--mode",
            "act",
            "--output-dir",
            str(output_dir),
            "--address-threshold",
            "90",
            "--name-threshold",
            "85",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    written_paths = [Path(line) for line in result.stdout.splitlines()]
    assert len(written_paths) == 2
    assert {path.suffix for path in written_paths} == {".csv", ".pdf"}
    assert all(path.exists() for path in written_paths)
    assert all("imis_duplicate_candidates_act_" in path.name for path in written_paths)
