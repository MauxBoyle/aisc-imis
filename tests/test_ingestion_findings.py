"""Tests for the cross-source ingestion findings review report."""

from __future__ import annotations

import json
import subprocess
import sys

from aisc_imis.activity_history_records import read_activity_history_records
from aisc_imis.current_member_records import read_current_member_records
from aisc_imis.historical_snapshot_records import read_historical_snapshot_records
from aisc_imis.ingestion_findings import build_ingestion_findings_report
from aisc_imis.membership_change_records import read_membership_change_records


def _write_references(tmp_path):
    reference_directory = tmp_path / "reference"
    reference_directory.mkdir(exist_ok=True)
    (reference_directory / "member_types.csv").write_text(
        "code,meaning\nACT,Active\n", encoding="utf-8"
    )
    (reference_directory / "statuses.csv").write_text(
        "code,meaning\nA,Active\n", encoding="utf-8"
    )
    (reference_directory / "snapshot_dates.csv").write_text(
        "snapshot_date\n2026-10-15\n", encoding="utf-8"
    )
    (reference_directory / "lifecycle-evidence-taxonomy.csv").write_text(
        "source,field,code,evidence_class,assertion_level,draft_lifecycle_name,countability_effect\n"
        "Membership changes,Change Type,JOIN,event,candidate,joined,countable\n"
        "Activity history,Activity Type,PAY,payment,evidence,other observed,not_countable\n",
        encoding="utf-8",
    )
    return reference_directory


def _write_sources(tmp_path):
    current = tmp_path / "current.csv"
    current.write_text(
        "iMIS Id,Member Type,Is Company,Is Member,Last Updated,Status,Name\n"
        "001,ACT,maybe,True,2026-10-15,A,Ada <Admin>\n"
        ",ACT,True,True,,A,Rejected\n"
        "001,ACT,False,True,2026-10-15,A,Duplicate\n"
        "002,NEW,True,True,2026-10-15,ZZ,Unknown\n",
        encoding="utf-8",
    )
    history = tmp_path / "history.csv"
    history.write_text(
        "iMIS Id,Member Type,Is Company,Is Member,Last Updated,Status\n"
        "003,ACT,True,True,2026-10-15,A\n"
        "003,ACT,False,True,2026-10-15,A\n",
        encoding="utf-8",
    )
    changes = tmp_path / "changes.csv"
    changes.write_text(
        "ChangeID,Ordinal,Change Type,Member Type,ChangeUpdate,ChangeCreated,Status\n"
        "C1,1,JOIN,ACT,2026-10-15,2026-10-14,A\n"
        "C1,1,JOIN,ACT,2026-10-15,2026-10-14,A\n",
        encoding="utf-8",
    )
    activity = tmp_path / "activity.csv"
    activity.write_text(
        "iMIS Id,Sequence,A_Transaction,Activity Type,Effective Date,Member Type,Is a Company\n"
        "004,1,T1,OTHER,2026-10-15,ACT,True\n",
        encoding="utf-8",
    )
    return current, history, changes, activity


def _report(tmp_path):
    reference_directory = _write_references(tmp_path)
    current, history, changes, activity = _write_sources(tmp_path)
    return build_ingestion_findings_report(
        current=read_current_member_records(current, reference_directory),
        historical=read_historical_snapshot_records(history, reference_directory),
        membership_changes=read_membership_change_records(changes, reference_directory),
        activity_history=read_activity_history_records(activity, reference_directory),
    )


def test_report_has_deterministic_full_sha256_ids_and_source_totals(tmp_path):
    first = _report(tmp_path).to_dict()
    second = _report(tmp_path).to_dict()

    assert first == second
    assert len(first["findings"][0]["id"]) == 64
    assert first["sources"] == [
        {"source": "current", "accepted_observations": 3, "rejected_rows": 1, "findings": 6},
        {"source": "historical", "accepted_observations": 2, "rejected_rows": 0, "findings": 2},
        {"source": "membership_changes", "accepted_observations": 2, "rejected_rows": 0, "findings": 2},
        {"source": "activity_history", "accepted_observations": 1, "rejected_rows": 0, "findings": 1},
    ]


def test_report_classifies_and_retains_row_evidence_with_safe_markdown(tmp_path):
    report = _report(tmp_path)
    findings = report.to_dict()["findings"]

    assert {finding["category"] for finding in findings} == {
        "rejected",
        "partial",
        "duplicate",
        "conflict",
        "unknown_code",
    }
    rejected = next(finding for finding in findings if finding["category"] == "rejected")
    assert rejected["validation_failures"] == [
        {"field": "iMIS Id", "code": "required", "message": "iMIS Id is required and cannot be blank."},
        {"field": "Last Updated", "code": "required", "message": "Last Updated is required and cannot be blank."},
    ]
    assert rejected["raw_fields"]["Name"] == "Rejected"
    partial = next(finding for finding in findings if finding["category"] == "partial")
    assert partial["raw_fields"]["Name"] == "Ada <Admin>"
    assert "Ada &lt;Admin&gt;" in report.to_markdown()


def test_cli_requires_inputs_and_writes_default_report_names(tmp_path):
    command = [sys.executable, "scripts/report_ingestion_findings.py"]
    missing_inputs = subprocess.run(command, capture_output=True, text=True)
    assert missing_inputs.returncode == 2

    reference_directory = _write_references(tmp_path)
    current, history, changes, activity = _write_sources(tmp_path)
    output_directory = tmp_path / "output"
    generated = subprocess.run(
        command
        + [
            "--current", str(current),
            "--history", str(history),
            "--membership-changes", str(changes),
            "--activity-history", str(activity),
            "--reference-directory", str(reference_directory),
            "--output-directory", str(output_directory),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert generated.returncode == 0, generated.stderr

    payload = json.loads((output_directory / "ingestion-findings.json").read_text())
    assert payload["findings"]
    assert (output_directory / "ingestion-findings.md").exists()
