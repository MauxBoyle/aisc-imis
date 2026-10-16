"""Synthetic quarterly expulsion lists."""

import csv
from dataclasses import replace
from datetime import date
from pathlib import Path

from aisc_imis.board_pending_actions import (
    ActionKind,
    ActionRevision,
    ActionStatus,
    BoardAction,
    BoardPendingActions,
)
from aisc_imis.evidence_ledger import (
    CandidateLifecycleEvent,
    InterpretationStatus,
    SnapshotStateObservation,
)
from aisc_imis.lifecycle_rules import load_lifecycle_rules
from aisc_imis.m5_expulsions import build_m5_expulsions, write_m5_csv
from aisc_imis.member_ledger import build_member_evidence_ledger
from aisc_imis.normalization_contracts import SourceReference
from aisc_imis.quarterly_board_movements import classify_quarterly_movements

START, END = date(2027, 1, 1), date(2027, 4, 1)
RULES = load_lifecycle_rules(Path(__file__).parents[1] / "data/reference")


def snapshot(key):
    return tuple(
        SnapshotStateObservation(
            key,
            f"{field}={value}",
            SourceReference("synthetic.csv", key),
            observed_date=date(2026, 12, 31),
            recorded_date=date(2026, 12, 31),
        )
        for field, value in (
            ("member_type", "ACT"),
            ("category", "A"),
            ("is_member", True),
            ("is_company", False),
        )
    )


def expulsion(key, effective, recorded=None):
    return CandidateLifecycleEvent(
        key,
        "expelled",
        (SourceReference("synthetic.csv", f"{key}-expelled"),),
        "Synthetic expulsion",
        effective_date=effective,
        recorded_date=recorded or effective,
    )


def board(action_id, member_ref, *states, imis_id=None):
    revisions = tuple(
        ActionRevision(
            action_id,
            f"{action_id}-{i}",
            f"{action_id}-{i - 1}" if i > 1 else None,
            member_ref,
            ActionKind.EXPULSION,
            status,
            status_date,
            "secretary",
            "Synthetic action",
            f"minutes/{action_id}-{i}",
            imis_id=imis_id,
            effective_date=effective,
            imis_record_ref=f"imis/{action_id}"
            if status is ActionStatus.RECORDED_IN_IMIS
            else None,
        )
        for i, (status, status_date, effective) in enumerate(states, 1)
    )
    return BoardAction(action_id, member_ref, ActionKind.EXPULSION, revisions)


def classify(records=(), actions=(), cutoff=date(2027, 4, 15)):
    return classify_quarterly_movements(
        build_member_evidence_ledger(records).entries,
        START,
        END,
        cutoff,
        RULES,
        BoardPendingActions(tuple(actions), ()),
        ("A",),
    )


def test_pending_status_at_cutoff_and_proposal_never_completes():
    proposal = board("p", "local-p", (ActionStatus.PROPOSED, START, None))
    approved = board(
        "a",
        "local-a",
        (ActionStatus.PROPOSED, date(2027, 2, 1), None),
        (ActionStatus.APPROVED, date(2027, 4, 10), date(2027, 3, 1)),
    )
    rejected = board(
        "r",
        "local-r",
        (ActionStatus.PROPOSED, START, None),
        (ActionStatus.REJECTED, date(2027, 2, 2), None),
    )
    withdrawn = board(
        "w",
        "local-w",
        (ActionStatus.PROPOSED, START, None),
        (ActionStatus.WITHDRAWN, date(2027, 2, 3), None),
    )
    records = (*snapshot("local-a"),)
    early = build_m5_expulsions(
        classify(records, (proposal, approved, rejected, withdrawn), date(2027, 4, 5)),
        BoardPendingActions((proposal, approved, rejected, withdrawn), ()),
    )
    assert {row.action_id for row in early.pending_proposals} == {"p", "a"}
    assert early.completed_expulsions == ()
    assert {f.code for f in early.findings} >= {
        "m5_rejected_action",
        "m5_withdrawn_action",
    }
    late = build_m5_expulsions(
        classify(records, (proposal, approved, rejected, withdrawn)),
        BoardPendingActions((proposal, approved, rejected, withdrawn), ()),
    )
    assert {row.action_id for row in late.pending_proposals} == {"p"}
    assert len(late.completed_expulsions) == 1
    row = late.completed_expulsions[0]
    assert (
        row.action_id,
        row.action_status,
        row.proposed_date,
        row.approved_date,
        row.effective_date,
    ) == ("a", "approved", date(2027, 2, 1), date(2027, 4, 10), date(2027, 3, 1))
    assert row.operational_history == "not_recorded"


def test_operational_match_and_later_recording_keep_one_completed_row():
    action = board(
        "a",
        "local-a",
        (ActionStatus.PROPOSED, START, None),
        (ActionStatus.APPROVED, date(2027, 2, 2), date(2027, 2, 1)),
        (ActionStatus.RECORDED_IN_IMIS, date(2027, 4, 10), None),
        imis_id="001",
    )
    records = (*snapshot("001"), expulsion("001", date(2027, 2, 1), date(2027, 4, 10)))
    early = build_m5_expulsions(
        classify(records, (action,), date(2027, 4, 5)),
        BoardPendingActions((action,), ()),
    )
    assert len(early.completed_expulsions) == 1
    assert early.completed_expulsions[0].operational_history == "not_recorded"
    late = build_m5_expulsions(
        classify(records, (action,)), BoardPendingActions((action,), ())
    )
    assert len(late.completed_expulsions) == 1
    row = late.completed_expulsions[0]
    assert (
        row.subject_key,
        row.action_status,
        row.recorded_date,
        row.operational_history,
    ) == ("001", "recorded-in-iMIS", date(2027, 4, 10), "recorded")
    assert "synthetic.csv:001-expelled" in row.lifecycle_evidence_refs
    assert row.board_evidence_refs
    assert late.counts == {"pending_proposals": 0, "completed_expulsions": 1}


def test_boundaries_ambiguity_and_count_discrepancies():
    first = board("a", "one", (ActionStatus.APPROVED, START, START), imis_id="001")
    second = board("b", "two", (ActionStatus.APPROVED, START, START), imis_id="001")
    outside = board("outside", "three", (ActionStatus.PROPOSED, END, None))
    records = (*snapshot("001"), expulsion("001", START))
    actions = BoardPendingActions((first, second, outside), ())
    movements = classify(records, actions.actions)
    result = build_m5_expulsions(movements, actions)
    assert len(result.completed_expulsions) == 1
    assert result.completed_expulsions[0].action_id is None
    assert result.pending_proposals == ()
    assert "m5_ambiguous_board_match" in {f.code for f in result.findings}
    broken = replace(movements, counted=())
    difference = build_m5_expulsions(broken, actions)
    assert {f.code for f in difference.findings} >= {"m5_balance_count_difference"}


def test_csv_has_dates_status_and_evidence(tmp_path):
    proposal = board("p", "local-p", (ActionStatus.PROPOSED, START, None))
    result = build_m5_expulsions(
        classify((*snapshot("001"), expulsion("001", START)), (proposal,)),
        BoardPendingActions((proposal,), ()),
    )
    pending_path, completed_path = write_m5_csv(result, tmp_path / "reports")
    with pending_path.open(newline="", encoding="utf-8") as file:
        pending = list(csv.DictReader(file))
    with completed_path.open(newline="", encoding="utf-8") as file:
        completed = list(csv.DictReader(file))
    assert pending[0]["action_status"] == "proposed"
    assert pending[0]["report_cutoff"] == "2027-04-15"
    assert completed[0]["effective_date"] == "2027-01-01"
    assert completed[0]["operational_history"] == "recorded"
    assert "ledger:" in completed[0]["lifecycle_evidence_refs"]


def test_rejected_or_different_date_board_action_does_not_label_operational_event():
    rejected = board(
        "r", "local-r", (ActionStatus.REJECTED, START, START), imis_id="001"
    )
    other_date = board(
        "d", "local-d", (ActionStatus.APPROVED, START, date(2027, 2, 1)), imis_id="001"
    )
    records = (*snapshot("001"), expulsion("001", START))
    actions = BoardPendingActions((rejected, other_date), ())
    result = build_m5_expulsions(classify(records, actions.actions), actions)
    assert len(result.completed_expulsions) == 1
    assert result.completed_expulsions[0].action_id is None
    assert result.completed_expulsions[0].action_status == "operational"


def test_incomplete_balance_keeps_confirmed_expulsion_and_finding():
    uncertain = CandidateLifecycleEvent(
        "unknown",
        "expelled",
        (SourceReference("synthetic.csv", "uncertain"),),
        "Uncertain event",
        effective_date=date(2027, 3, 1),
        recorded_date=date(2027, 3, 1),
        interpretation_status=InterpretationStatus.AMBIGUOUS,
    )
    records = (*snapshot("001"), expulsion("001", START), uncertain)
    result = build_m5_expulsions(classify(records), BoardPendingActions((), ()))
    assert len(result.completed_expulsions) == 1
    assert result.counts["completed_expulsions"] == 1
    assert "m5_incomplete_balance" in {finding.code for finding in result.findings}
