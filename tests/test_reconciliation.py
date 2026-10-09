"""Tests for Certified Domestic Fabricator reconciliation reports."""

import csv
import subprocess
import sys
from pathlib import Path

import pytest

from aisc_imis.reconciliation import (
    REPORT_COLUMNS,
    read_imis_records,
    read_salesforce_records,
    reconcile_records,
    write_reconciliation_reports,
)


def _write_csv(path: Path, rows: list[dict[str, str]], *, bom: bool = False) -> None:
    with path.open("w", encoding="utf-8-sig" if bom else "utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def _salesforce(
    record_id: str, name: str, street: str, *, certified: str = "True", imis_id: str = ""
) -> dict[str, str]:
    return {
        "Id": record_id,
        "Name": name,
        "BillingStreet": street,
        "BillingCity": "Austin",
        "BillingState": "TX",
        "BillingPostalCode": "78701",
        "BillingCountry": "USA",
        "Certified_Fabricator__c": certified,
        "IMISID__c": imis_id,
        "Is_active_in_IMIS_for_Member_Discount__c": "False",
    }


def _imis(
    record_id: str, company: str, address: str, *, member_type: str = "ACT", status: str = "A"
) -> dict[str, str]:
    return {
        "iMIS Id": record_id,
        "Company": company,
        "Full Address": address,
        "Member Type": member_type,
        "Status": status,
    }


def test_reconciliation_groups_records_and_keeps_leading_zero_ids(tmp_path):
    salesforce_path = tmp_path / "salesforce.csv"
    imis_path = tmp_path / "imis.csv"
    _write_csv(
        salesforce_path,
        [
            _salesforce("001", "Acme Steel", "10 Main St", imis_id="0007"),
            _salesforce("002", "Acme Steel", "10 Main St", certified="False"),
            {
                **_salesforce("003", "No Address", ""),
                "BillingCity": "",
                "BillingState": "",
                "BillingPostalCode": "",
                "BillingCountry": "",
            },
        ],
        bom=True,
    )
    _write_csv(
        imis_path,
        [
            _imis("0007", "Acme Steel", "10 Main Street, Austin, TX 78701, USA"),
            _imis("8", "Acme Steel Works", "10 Main Street, Austin, TX 78701, USA"),
        ],
    )

    results = reconcile_records(
        read_salesforce_records(salesforce_path), read_imis_records(imis_path)
    )

    assert [(result["salesforce_id"], result["match_group"]) for result in results] == [
        ("001", "many"),
        ("001", "many"),
        ("002", "many"),
        ("002", "many"),
        ("003", "none"),
    ]
    assert results[0]["salesforce_imis_id"] == "0007"
    assert results[-1]["candidate_count"] == 0


def test_one_match_status_and_id_verdicts_and_report_outputs(tmp_path):
    salesforce_path = tmp_path / "salesforce.csv"
    imis_path = tmp_path / "imis.csv"
    _write_csv(salesforce_path, [_salesforce("001", "Acme Steel", "10 Main St", imis_id="0007")])
    _write_csv(imis_path, [_imis("0007", "Acme Steel", "10 Main Street, Austin, TX 78701, USA")])

    results = reconcile_records(
        read_salesforce_records(salesforce_path), read_imis_records(imis_path)
    )
    assert results[0]["match_group"] == "one"
    assert results[0]["imis_id_matches"] is True
    assert results[0]["membership_status_matches"] is True
    assert results[0]["address_score"] >= 90
    assert results[0]["name_score"] >= 50

    csv_path, pdf_path = write_reconciliation_reports(
        results, tmp_path / "processed", address_threshold=90, name_threshold=50,
        timestamp="20261009T101112",
    )
    assert csv_path.name == "certified_fabricator_reconciliation_20261009T101112.csv"
    with csv_path.open(newline="") as file:
        rows = list(csv.DictReader(file))
    assert list(rows[0]) == REPORT_COLUMNS
    assert rows[0]["candidate_member_type"] == "ACT"
    assert rows[0]["salesforce_active_for_member_discount"] == "False"
    assert "salesforce_certified_fabricator" not in rows[0]
    assert rows[0]["membership_status_matches"] == "True"
    assert pdf_path.read_bytes().startswith(b"%PDF")
    assert pdf_path.stat().st_size > 100


def test_status_rules_and_different_zip_codes_do_not_block_matching(tmp_path):
    salesforce_path = tmp_path / "salesforce.csv"
    imis_path = tmp_path / "imis.csv"
    shared_address = "1000 Very Long Industrial Boulevard Building Seven Suite 400 North Austin Texas"
    salesforce = _salesforce("001", "Acme Steel", shared_address, certified="False")
    salesforce["BillingCity"] = ""
    salesforce["BillingState"] = ""
    salesforce["BillingPostalCode"] = "11111"
    salesforce["BillingCountry"] = ""
    _write_csv(salesforce_path, [salesforce])
    _write_csv(
        imis_path,
        [_imis("7", "Acme Steel", f"{shared_address}, 99999", member_type="ACT", status="A")],
    )

    results = reconcile_records(
        read_salesforce_records(salesforce_path), read_imis_records(imis_path)
    )

    assert results[0]["match_group"] == "one"
    assert results[0]["address_score"] >= 90
    assert results[0]["membership_status_matches"] is False


def test_country_variants_do_not_reduce_reconciliation_address_score(tmp_path):
    salesforce_path = tmp_path / "salesforce.csv"
    imis_path = tmp_path / "imis.csv"
    salesforce = _salesforce("001", "US Stair Corporation", "2100 S. 11th Avenue")
    salesforce.update(
        {
            "BillingCity": "Phoenix",
            "BillingState": "AZ",
            "BillingPostalCode": "85007",
            "BillingCountry": "United States",
        }
    )
    _write_csv(salesforce_path, [salesforce])
    _write_csv(
        imis_path,
        [_imis("3410334", "US Stair Corporation", "2100 S 11th Avenue\nPhoenix, AZ 85007")],
    )

    results = reconcile_records(
        read_salesforce_records(salesforce_path), read_imis_records(imis_path)
    )

    assert results[0]["match_group"] == "one"
    assert results[0]["address_score"] == 100


def test_required_headers_and_cli(tmp_path):
    salesforce_path = tmp_path / "salesforce.csv"
    imis_path = tmp_path / "imis.csv"
    salesforce_path.write_text("Id,Name\n001,Acme\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Missing required Salesforce CSV columns"):
        read_salesforce_records(salesforce_path)

    _write_csv(salesforce_path, [_salesforce("001", "Acme Steel", "10 Main St")])
    _write_csv(imis_path, [_imis("7", "Acme Steel", "10 Main Street, Austin, TX 78701, USA")])
    result = subprocess.run(
        [sys.executable, "scripts/reconcile_certified_fabricators.py", str(salesforce_path), str(imis_path), "--output-dir", str(tmp_path / "out")],
        check=True, capture_output=True, text=True,
    )
    assert len(result.stdout.splitlines()) == 2


def test_current_certified_fabricator_export_columns_are_supported(tmp_path):
    salesforce_path = tmp_path / "salesforce.csv"
    _write_csv(
        salesforce_path,
        [
            {
                "Name": "Acme Steel",
                "BillingStreet": "10 Main St",
                "BillingCity": "Austin",
                "BillingState": "TX",
                "BillingPostalCode": "78701",
                "BillingCountry": "USA",
                "Certification_ID__c": "2020-02-05-004182F",
                "IMISID__c": "0007",
                "InIMIS__c": "True",
                "Is_active_in_IMIS_for_Member_Discount__c": "False",
            }
        ],
    )

    records = read_salesforce_records(salesforce_path)

    assert records[0]["salesforce_id"] == "2020-02-05-004182F"
    assert records[0]["in_imis"] is True
    assert records[0]["active_for_member_discount"] is False
