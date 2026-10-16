"""Invented evidence for the M2/M3 selection and IQA display rules."""

import csv
from datetime import date
from pathlib import Path

import pytest

from aisc_imis.board_pending_actions import (
    ActionKind,
    ActionRevision,
    ActionStatus,
    BoardAction,
    BoardPendingActions,
)
from aisc_imis.evidence_ledger import CandidateLifecycleEvent, SnapshotStateObservation
from aisc_imis.lifecycle_rules import load_lifecycle_rules
from aisc_imis.member_ledger import build_member_evidence_ledger
from aisc_imis.new_members import (
    build_m2_m3_new_members,
    read_new_members_iqa,
    write_m2_m3_csv,
)
from aisc_imis.normalization_contracts import SourceReference
from aisc_imis.quarterly_board_movements import classify_quarterly_movements

START, END, CUTOFF = date(2027, 1, 1), date(2027, 4, 1), date(2027, 4, 15)
RULES = load_lifecycle_rules(Path(__file__).parents[1] / "data/reference")
HEADER = (
    "Join Date",
    "Member Type",
    "iMIS Id",
    "Company",
    "Full Address",
    "Category",
    "Tonnage Est",
    "Reference Contact",
    "Reference Company",
)


def iqa_file(path, rows):
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(HEADER)
        writer.writerows(rows)
    return read_new_members_iqa(path)


def detail(key, kind="ACT", join_date="2027-01-01", company="Example"):
    return (join_date, kind, key, company, "Address", "A", "12", "Pat", "Referral")


def snapshot(key, when=date(2026, 12, 31)):
    return tuple(
        SnapshotStateObservation(
            key,
            f"{field}={value}",
            SourceReference("invented", key),
            effective_date=when,
            recorded_date=when,
        )
        for field, value in (
            ("member_type", "FACT"),
            ("category", "A"),
            ("is_member", True),
            ("is_company", False),
        )
    )


def join(key, kind, effective, recorded=None):
    return CandidateLifecycleEvent(
        key,
        "joined",
        (SourceReference("invented", f"join-{key}"),),
        "Invented join",
        member_type=kind,
        effective_date=effective,
        recorded_date=recorded or effective,
    )


def board(action_id, key, status, status_date, effective, kind="ACT"):
    revision = ActionRevision(
        action_id,
        f"{action_id}-1",
        None,
        key,
        ActionKind.NEW_MEMBER_APPROVAL,
        status,
        status_date,
        "Secretary",
        "Invented action",
        "minutes/p1",
        imis_id=key,
        effective_date=effective,
        member_type=kind,
    )
    return BoardAction(action_id, key, ActionKind.NEW_MEMBER_APPROVAL, (revision,))


def classify(records=(), actions=(), cutoff=CUTOFF):
    return classify_quarterly_movements(
        build_member_evidence_ledger(records).entries,
        START,
        END,
        cutoff,
        RULES,
        BoardPendingActions(tuple(actions), ()),
        ("A",),
        join_measures={"ACT": "M2", "ASSOC": "M3"},
    )


def test_reader_preserves_text_ids_columns_and_source_location(tmp_path):
    path = tmp_path / "iqa.csv"
    rows = iqa_file(path, [detail("00123", join_date="3/31/2027")])
    assert len(rows) == 1
    row = rows[0]
    assert (row.imis_id, row.join_date, row.member_type) == (
        "00123",
        "3/31/2027",
        "ACT",
    )
    assert (row.company, row.full_address, row.category, row.tonnage_est) == (
        "Example",
        "Address",
        "A",
        "12",
    )
    assert (row.reference_contact, row.reference_company) == ("Pat", "Referral")
    assert (row.source_file, row.source_row) == (str(path), 2)


def test_reader_requires_template_columns_and_blank_fields_get_findings(tmp_path):
    path = tmp_path / "incomplete.csv"
    path.write_text("iMIS Id,Company\n001,Example\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        read_new_members_iqa(path)
    iqa = iqa_file(
        tmp_path / "valid.csv",
        [("2027-01-01", "ACT", "001", "", "Address", "A", "12", "Pat", "Referral")],
    )
    movements = classify((*snapshot("001"), join("001", "ACT", START)))
    result = build_m2_m3_new_members(movements, iqa, BoardPendingActions((), ()))
    assert result.m2[0].company == ""
    assert any(f.code == "missing_iqa_field" for f in result.findings)


def test_effective_boundaries_late_recording_and_join_date_disagreement(tmp_path):
    records = (
        *snapshot("001"),
        join("001", "ACT", START, date(2027, 4, 10)),
        *snapshot("002"),
        join("002", "ASSOC", date(2027, 3, 31)),
        *snapshot("003"),
        join("003", "ACT", END),
    )
    iqa = iqa_file(
        tmp_path / "iqa.csv",
        [
            detail("001", join_date="2026-12-15"),
            detail("002", "ASSOC", "2027-04-02"),
            detail("003"),
        ],
    )
    result = build_m2_m3_new_members(
        classify(records), iqa, BoardPendingActions((), ())
    )
    assert ([row.imis_id for row in result.m2], [row.imis_id for row in result.m3]) == (
        ["001"],
        ["002"],
    )
    assert result.m2[0].effective_date == START
    assert result.m2[0].recorded_date == date(2027, 4, 10)
    assert result.m2[0].join_date == "2026-12-15"
    assert result.m2[0].operational_status == "joined"
    assert result.m2[0].lifecycle_evidence_refs
    assert result.counts == {"M2": 1, "M3": 1}
    assert (
        build_m2_m3_new_members(
            classify(records, cutoff=date(2027, 4, 5)), iqa, BoardPendingActions((), ())
        ).m2
        == ()
    )


def test_board_approval_near_cutoff_and_preapproval_operational_join(tmp_path):
    action = board(
        "approved",
        "004",
        ActionStatus.APPROVED,
        date(2027, 4, 10),
        date(2027, 3, 31),
        "ASSOC",
    )
    rejected = board("rejected", "005", ActionStatus.REJECTED, START, START)
    withdrawn = board("withdrawn", "006", ActionStatus.WITHDRAWN, START, START)
    actions = BoardPendingActions((action, rejected, withdrawn), ())
    iqa = iqa_file(tmp_path / "iqa.csv", [detail("004", "ASSOC"), detail("005")])
    before = build_m2_m3_new_members(
        classify(actions=actions.actions, cutoff=date(2027, 4, 5)), iqa, actions
    )
    after = build_m2_m3_new_members(classify(actions=actions.actions), iqa, actions)
    assert before.m3 == ()
    assert [row.imis_id for row in after.m3] == ["004"]
    assert (after.m3[0].board_action_status, after.m3[0].approved_date) == (
        "approved",
        date(2027, 4, 10),
    )
    assert after.m3[0].board_evidence_ref == "approved:minutes/p1"
    preapproval = BoardPendingActions(
        (board("pending", "007", ActionStatus.PROPOSED, START, START),), ()
    )
    operational = classify(
        (*snapshot("007"), join("007", "ACT", START)), preapproval.actions
    )
    output = build_m2_m3_new_members(operational, (), preapproval)
    assert len(output.m2) == 1
    assert output.m2[0].board_action_status == "proposed"


def test_missing_and_conflicting_iqa_keep_every_classified_join(tmp_path):
    records = (
        *snapshot("008"),
        join("008", "ACT", START),
        *snapshot("009"),
        join("009", "ASSOC", START),
    )
    iqa = iqa_file(
        tmp_path / "iqa.csv",
        [
            detail("009", "ASSOC", company="First"),
            detail("009", "ASSOC", company="Second"),
        ],
    )
    result = build_m2_m3_new_members(
        classify(records), iqa, BoardPendingActions((), ())
    )
    assert (len(result.m2), len(result.m3)) == (1, 1)
    assert result.m2[0].company == result.m3[0].company == ""
    assert {finding.code for finding in result.findings} == {
        "missing_iqa_match",
        "conflicting_iqa_matches",
    }
    assert result.m3[0].iqa_source_refs.endswith("iqa.csv:3")


def test_duplicate_iqa_and_csv_order_are_stable(tmp_path):
    records = (
        *snapshot("020"),
        join("020", "ACT", START),
        *snapshot("010"),
        join("010", "ACT", START),
    )
    iqa = iqa_file(tmp_path / "iqa.csv", [detail("020"), detail("020"), detail("010")])
    result = build_m2_m3_new_members(
        classify(records), iqa, BoardPendingActions((), ())
    )
    assert [row.imis_id for row in result.m2] == ["010", "020"]
    assert any(f.code == "duplicate_iqa_match" for f in result.findings)
    m2, m3 = write_m2_m3_csv(result, tmp_path / "reports")
    with m2.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    assert [row["imis_id"] for row in rows] == ["010", "020"]
    assert rows[1]["iqa_source_refs"].endswith(
        "iqa.csv:2; " + str(tmp_path / "iqa.csv") + ":3"
    )
    with m3.open(newline="", encoding="utf-8") as file:
        assert list(csv.DictReader(file)) == []


def test_operational_join_shows_board_history_and_iqa_type_disagreement(tmp_path):
    proposal = board("approval", "030", ActionStatus.PROPOSED, START, START)
    first = proposal.revisions[0]
    approved = ActionRevision(
        "approval",
        "approval-2",
        first.revision_id,
        "030",
        ActionKind.NEW_MEMBER_APPROVAL,
        ActionStatus.APPROVED,
        date(2027, 4, 10),
        "Secretary",
        "Invented action",
        "minutes/p2",
        imis_id="030",
        effective_date=START,
        member_type="ACT",
    )
    actions = BoardPendingActions(
        (
            BoardAction(
                "approval", "030", ActionKind.NEW_MEMBER_APPROVAL, (first, approved)
            ),
        ),
        (),
    )
    movements = classify((*snapshot("030"), join("030", "ACT", START)), actions.actions)
    iqa = iqa_file(tmp_path / "iqa.csv", [detail("030", "ASSOC")])
    result = build_m2_m3_new_members(movements, iqa, actions)
    assert (result.m2[0].proposed_date, result.m2[0].approved_date) == (
        START,
        date(2027, 4, 10),
    )
    assert result.m2[0].board_evidence_ref == "approval:minutes/p2"
    assert any(f.code == "iqa_member_type_disagreement" for f in result.findings)


def test_board_join_uses_id_from_earlier_visible_revision(tmp_path):
    proposed = ActionRevision(
        "approval",
        "approval-1",
        None,
        "member-reference",
        ActionKind.NEW_MEMBER_APPROVAL,
        ActionStatus.PROPOSED,
        START,
        "Secretary",
        "Invented action",
        "minutes/p1",
        imis_id="00123",
        member_type="ACT",
    )
    approved = ActionRevision(
        "approval",
        "approval-2",
        proposed.revision_id,
        proposed.member_ref,
        ActionKind.NEW_MEMBER_APPROVAL,
        ActionStatus.APPROVED,
        date(2027, 3, 31),
        "Secretary",
        "Invented action",
        "minutes/p2",
        effective_date=date(2027, 3, 31),
        member_type="ACT",
    )
    action = BoardAction(
        "approval", proposed.member_ref, ActionKind.NEW_MEMBER_APPROVAL,
        (proposed, approved),
    )
    actions = BoardPendingActions((action,), ())
    movements = classify(actions=actions.actions)
    assert movements.counted[0].subject_key == "member-reference"
    iqa = iqa_file(tmp_path / "iqa.csv", [detail("00123")])

    result = build_m2_m3_new_members(movements, iqa, actions)

    assert len(result.m2) == 1
    assert result.m2[0].imis_id == "00123"
    assert result.m2[0].company == "Example"
    assert result.m2[0].board_action_status == "approved"
    assert result.m2[0].board_evidence_ref == "approval:minutes/p2"
    assert not result.findings

    conflicting = ActionRevision(
        "approval",
        "approval-3",
        approved.revision_id,
        approved.member_ref,
        ActionKind.NEW_MEMBER_APPROVAL,
        ActionStatus.APPROVED,
        CUTOFF,
        "Secretary",
        "Invented action",
        "minutes/p3",
        imis_id="00999",
        effective_date=date(2027, 3, 31),
        member_type="ACT",
    )
    conflicting_action = BoardAction(
        "approval", proposed.member_ref, ActionKind.NEW_MEMBER_APPROVAL,
        (proposed, approved, conflicting),
    )
    conflicting_actions = BoardPendingActions((conflicting_action,), ())
    result = build_m2_m3_new_members(
        classify(actions=conflicting_actions.actions), iqa, conflicting_actions
    )
    assert result.m2[0].imis_id == ""
    assert result.m2[0].company == ""
    assert any(f.code == "conflicting_board_imis_ids" for f in result.findings)
