"""A complete Board package built from invented local exports."""

import csv
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from aisc_imis.board_report_package import BoardReportInputs, build_board_report_package


def _inputs(tmp_path):
    reference = tmp_path / "reference"
    shutil.copytree(Path(__file__).parents[1] / "data/reference", reference)
    with (reference / "lifecycle-evidence-taxonomy.csv").open("a", encoding="utf-8") as file:
        file.write("Membership changes,Change Type,JOIN,1,lifecycle-event candidate,possible inference,joined,increases,Invented reviewed mapping\n")
    with (reference / "snapshot_dates.csv").open("a", encoding="utf-8") as file:
        file.write("2026-10-15\n")
    files = {
        "current": "iMIS Id,Member Type,Is Company,Is Member,Last Updated,Status,Category\n001,ACT,True,True,2026-10-18,A,BEND\n",
        "history": "iMIS Id,Member Type,Is Company,Is Member,Last Updated,Status,Category\n001,ACT,True,True,2026-10-14,A,BEND\n002,FACT,True,True,2026-10-15,A,BEND\n",
        "changes": "ChangeID,Ordinal,Change Type,Member Type,ChangeUpdate,ChangeCreated,Status\n002,1,JOIN,ACT,2026-10-17,2026-10-17,A\n",
        "activity": "iMIS Id,Sequence,A_Transaction,Activity Type,Effective Date,Member Type,Is a Company\n",
        "iqa": "Join Date,Member Type,iMIS Id,Company,Full Address,Category,Tonnage Est,Reference Contact,Reference Company\n2026-10-17,ACT,002,Invented Company,123 Main St,BEND,5,Pat,Referral\n",
        "board": '{"version": 1, "revisions": []}\n',
        "reviews": '{"reviews": []}\n',
    }
    paths = {}
    for name, content in files.items():
        paths[name] = (
            tmp_path / f"{name}.{'json' if name in {'board', 'reviews'} else 'csv'}"
        )
        paths[name].write_text(content, encoding="utf-8")
    return BoardReportInputs(
        period_start=date(2026, 10, 16),
        as_of_date=date(2026, 10, 18),
        board_cutoff=date(2026, 10, 20),
        current_export_date=date(2026, 10, 18),
        current_csv=paths["current"],
        history_csv=paths["history"],
        membership_changes_csv=paths["changes"],
        activity_history_csv=paths["activity"],
        new_members_iqa_csv=paths["iqa"],
        board_actions_json=paths["board"],
        review_registry_json=paths["reviews"],
        reference_directory=reference,
        output_directory=tmp_path / "report",
    )


def test_complete_package_is_traceable_and_repeatable(tmp_path):
    inputs = _inputs(tmp_path)
    result = build_board_report_package(inputs)
    expected = {
        "m1_membership_numbers.csv",
        "m2_new_members.csv",
        "m3_new_members.csv",
        "m4_resignations.csv",
        "m4_reinstatements.csv",
        "m5_pending_proposals.csv",
        "m5_completed_expulsions.csv",
        "member_drilldown.csv",
        "member_evidence.csv",
        "findings.csv",
        "manifest.json",
    }
    assert {path.name for path in result.output_files} == expected
    with (inputs.output_directory / "m1_membership_numbers.csv").open() as file:
        overall = next(csv.DictReader(file))
        assert overall["operational_as_of_date"] == "2026-10-18"
        assert overall["reviewed_adjustments"] == "0"
        assert overall["joined"] == "1"
    with (inputs.output_directory / "m2_new_members.csv").open() as file:
        m2 = list(csv.DictReader(file))
    assert len(m2) == 1
    assert m2[0]["imis_id"] == "002"
    assert m2[0]["company"] == "Invented Company"
    assert m2[0]["lifecycle_evidence_refs"]
    with (inputs.output_directory / "member_evidence.csv").open() as file:
        rows = list(csv.DictReader(file))
    assert any(
        row["subject_key"] == "001" and row["observed_date"] == "2026-10-18"
        for row in rows
    )
    with (inputs.output_directory / "member_drilldown.csv").open() as file:
        drilldown = list(csv.DictReader(file))
    assert any(row["subject_key"] == "001" and row["evidence_ids"] for row in drilldown)
    manifest = json.loads((inputs.output_directory / "manifest.json").read_text())
    assert manifest["period_end_exclusive"] == "2026-10-19"
    assert (
        manifest["inputs"]["current_csv"]["sha256"]
        == hashlib.sha256(inputs.current_csv.read_bytes()).hexdigest()
    )
    for name, fingerprint in manifest["outputs"].items():
        assert (
            fingerprint
            == hashlib.sha256((inputs.output_directory / name).read_bytes()).hexdigest()
        )
    original = {path.name: path.read_bytes() for path in result.output_files}
    build_board_report_package(inputs)
    assert original == {path.name: path.read_bytes() for path in result.output_files}


def test_cutoff_and_missing_inputs_fail_before_writing(tmp_path):
    inputs = _inputs(tmp_path)
    with pytest.raises(ValueError, match="export date"):
        build_board_report_package(
            replace(inputs, current_export_date=date(2026, 10, 21))
        )
    assert not inputs.output_directory.exists()
    inputs.current_csv.unlink()
    with pytest.raises(FileNotFoundError, match="current_csv"):
        build_board_report_package(inputs)


def test_earlier_as_of_excludes_later_current_snapshot(tmp_path):
    inputs = _inputs(tmp_path)
    inputs = replace(inputs, as_of_date=date(2026, 10, 17))
    build_board_report_package(inputs)
    with (inputs.output_directory / "member_drilldown.csv").open() as file:
        member = next(csv.DictReader(file))
    assert member["closing_countability"] == "unknown"
    assert member["opening_countability"] == "unknown"
    with (inputs.output_directory / "member_evidence.csv").open() as file:
        current = [
            row
            for row in csv.DictReader(file)
            if row["source_references"].find("current.csv") >= 0
        ]
    assert all(row["recorded_date"] == "2026-10-18" for row in current)


def test_cli_and_review_registry_keep_findings_visible(tmp_path):
    inputs = _inputs(tmp_path)
    result = build_board_report_package(inputs)
    with (inputs.output_directory / "findings.csv").open() as file:
        findings = list(csv.DictReader(file))
    assert result.finding_count == len(findings)
    assert findings
    reconciliation = next(row for row in findings if row["source"] == "reconciliation")
    inputs.review_registry_json.write_text(
        json.dumps(
            {
                "reviews": [
                    {
                        "code": reconciliation["code"],
                        "member_key": reconciliation["subject_key"] or None,
                        "scope": reconciliation["message"],
                        "finding_id": reconciliation["finding_id"],
                        "reviewer": "Invented Reviewer",
                        "outcome": "explained",
                        "rationale": "Invented source gap",
                        "review_date": "2026-10-20",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    build_board_report_package(inputs)
    with (inputs.output_directory / "findings.csv").open() as file:
        reviewed = list(csv.DictReader(file))
    assert any(
        row["finding_id"] == reconciliation["finding_id"]
        and row["review_status"] == "explained"
        for row in reviewed
    )
    registry = json.loads(inputs.review_registry_json.read_text(encoding="utf-8"))
    registry["reviews"][0]["valid_through"] = "2026-10-19"
    inputs.review_registry_json.write_text(json.dumps(registry), encoding="utf-8")
    build_board_report_package(inputs)
    with (inputs.output_directory / "findings.csv").open() as file:
        expired = list(csv.DictReader(file))
    assert any(
        row["finding_id"] == reconciliation["finding_id"]
        and row["review_status"] == "expired"
        for row in expired
    )
    registry["reviews"][0]["finding_id"] = "0" * 64
    inputs.review_registry_json.write_text(json.dumps(registry), encoding="utf-8")
    build_board_report_package(inputs)
    with (inputs.output_directory / "findings.csv").open() as file:
        stale = list(csv.DictReader(file))
    assert any(
        row["finding_id"] == reconciliation["finding_id"]
        and row["review_status"] == "stale"
        for row in stale
    )
    args = []
    for name, value in vars(inputs).items():
        args.extend(
            (
                f"--{name.replace('_', '-')}",
                value.isoformat() if isinstance(value, date) else str(value),
            )
        )
    command = [
        sys.executable,
        str(Path(__file__).parents[1] / "scripts/build_board_report_package.py"),
        *args,
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=True)
    assert "Run ID:" in completed.stdout
