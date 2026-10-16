"""Invented members test effective periods and later knowledge cutoffs."""

from datetime import date
from pathlib import Path

import pytest

from aisc_imis.board_pending_actions import (
    ActionKind,
    ActionRevision,
    ActionStatus,
    BoardAction,
    BoardPendingActions,
    PossibleDuplicateAction,
)
from aisc_imis.evidence_ledger import CandidateLifecycleEvent, SnapshotStateObservation
from aisc_imis.lifecycle_period_movements import EvidenceCorrection
from aisc_imis.lifecycle_rules import load_lifecycle_rules
from aisc_imis.member_ledger import build_member_evidence_ledger
from aisc_imis.normalization_contracts import SourceReference
from aisc_imis.quarterly_board_movements import classify_quarterly_movements

START, END = date(2027, 1, 1), date(2027, 4, 1)
RULES = load_lifecycle_rules(Path(__file__).parents[1] / "data/reference")


def snapshot(key, member_type, when, recorded=None):
    return tuple(
        SnapshotStateObservation(
            key,
            f"{field}={value}",
            SourceReference("invented", f"{key}-{when}"),
            effective_date=when,
            recorded_date=recorded or when,
        )
        for field, value in (
            ("member_type", member_type),
            ("category", "A"),
            ("is_member", True),
            ("is_company", False),
        )
    )


def event(key, name, when, recorded=None, status=None, member_type=None):
    kwargs = {"interpretation_status": status} if status else {}
    return CandidateLifecycleEvent(
        key,
        name,
        (SourceReference("invented", f"{key}-{name}-{when}"),),
        "Invented lifecycle event",
        effective_date=when,
        recorded_date=recorded or when,
        member_type=member_type,
        **kwargs,
    )


def action(action_id, key, kind, status, status_date, effective=None, **extra):
    revision = ActionRevision(
        action_id,
        f"{action_id}-1",
        None,
        key,
        kind,
        status,
        status_date,
        "Invented secretary",
        "Invented reason",
        "minutes/p1",
        effective_date=effective,
        **extra,
    )
    return BoardAction(action_id, key, kind, (revision,))


def classify(records=(), actions=(), cutoff=date(2027, 4, 15), duplicates=()):
    ledger = build_member_evidence_ledger(records)
    return classify_quarterly_movements(
        ledger.entries,
        START,
        END,
        cutoff,
        RULES,
        BoardPendingActions(tuple(actions), tuple(duplicates)),
        ("A",),
    )


def test_effective_boundaries_and_late_recording():
    records = (
        *snapshot("early", "FACT", date(2026, 12, 31)),
        event("early", "joined", START, date(2027, 4, 10)),
        *snapshot("late", "FACT", date(2026, 12, 31)),
        event("late", "joined", END),
    )
    result = classify(records)
    assert [(row.subject_key, row.measure) for row in result.counted] == [
        ("early", "M2")
    ]
    assert result.counted[0].recorded_date == date(2027, 4, 10)
    assert classify(records, cutoff=date(2027, 4, 5)).counted == ()
    with pytest.raises(ValueError):
        classify(records, cutoff=date(2027, 3, 30))


def test_same_period_join_resignation_reinstatement_and_transfer():
    records = (
        *snapshot("one", "FACT", date(2026, 12, 31)),
        event("one", "joined", START),
        event("one", "resigned", date(2027, 2, 1)),
        event("one", "reinstated", date(2027, 3, 1)),
        *snapshot("move", "ACT", date(2026, 12, 31)),
        event("move", "transferred", date(2027, 2, 1)),
        *snapshot("move", "ASSOC", date(2027, 2, 1)),
    )
    result = classify(records)
    assert [(row.measure, row.action) for row in result.counted] == [
        ("M2", "joined"),
        ("M4", "resigned"),
        ("M4", "reinstated"),
    ]
    assert len(result.category_transfers) == 0
    assert len(result.membership_grouping_transfers) == 1
    assert result.operational_total_change == 1
    assert result.operational_balance.overall.difference == 0


def test_board_actions_and_uncertain_states_stay_visible():
    actions = (
        action(
            "add",
            "new",
            ActionKind.NEW_MEMBER_APPROVAL,
            ActionStatus.APPROVED,
            date(2027, 4, 5),
            START,
        ),
        action(
            "expel",
            "old",
            ActionKind.EXPULSION,
            ActionStatus.APPROVED,
            date(2027, 2, 2),
            date(2027, 2, 1),
        ),
        action("proposal", "old", ActionKind.EXPULSION, ActionStatus.PROPOSED, START),
        action(
            "correction",
            "other",
            ActionKind.CORRECTION,
            ActionStatus.APPROVED,
            START,
            desired_category="B",
        ),
        action(
            "dup", "new", ActionKind.NEW_MEMBER_APPROVAL, ActionStatus.APPROVED, START
        ),
    )
    duplicate = PossibleDuplicateAction(
        "new", ActionKind.NEW_MEMBER_APPROVAL, ("add", "dup")
    )
    result = classify(
        (
            *snapshot("old", "ACT", date(2026, 12, 31)),
            *snapshot("other", "ACT", date(2026, 12, 31)),
        ),
        actions,
        duplicates=(duplicate,),
    )
    assert any(
        row.measure == "M5" and row.action_id == "expel" for row in result.counted
    )
    assert {row.action_id for row in result.noncounted} >= {
        "proposal",
        "correction",
        "add",
        "dup",
    }
    assert all(row.reason for row in result.noncounted)
    assert result.board_adjusted_total_change is None or isinstance(
        result.board_adjusted_total_change, int
    )


def test_recorded_board_action_does_not_duplicate_operational_join():
    records = (
        *snapshot("new", "FACT", date(2026, 12, 31)),
        event("new", "joined", START, date(2027, 4, 10)),
    )
    approved = action(
        "add",
        "new",
        ActionKind.NEW_MEMBER_APPROVAL,
        ActionStatus.APPROVED,
        START,
        START,
    )
    revision = approved.revisions[0]
    recorded = ActionRevision(
        "add",
        "add-2",
        revision.revision_id,
        "new",
        ActionKind.NEW_MEMBER_APPROVAL,
        ActionStatus.RECORDED_IN_IMIS,
        date(2027, 4, 10),
        "Invented secretary",
        "Invented reason",
        "minutes/p1",
        effective_date=START,
        imis_record_ref="invented-join",
    )
    result = classify(
        records,
        (
            BoardAction(
                "add", "new", ActionKind.NEW_MEMBER_APPROVAL, (revision, recorded)
            ),
        ),
    )
    assert len(result.counted) == 1
    assert result.counted[0].evidence
    assert any(row.action_id == "add" for row in result.noncounted)


def test_unresolved_event_makes_total_indeterminate():
    from aisc_imis.evidence_ledger import InterpretationStatus

    result = classify(
        (
            *snapshot("one", "FACT", date(2026, 12, 31)),
            event("one", "joined", START, status=InterpretationStatus.UNRESOLVED),
        )
    )
    assert result.operational_total_change is None
    assert any(
        finding.code == "unresolved_lifecycle_evidence" for finding in result.findings
    )


def test_late_board_approval_is_placed_by_effective_date():
    approved = action(
        "add",
        "new",
        ActionKind.NEW_MEMBER_APPROVAL,
        ActionStatus.APPROVED,
        date(2027, 4, 10),
        date(2027, 3, 31),
    )
    before = classify(actions=(approved,), cutoff=date(2027, 4, 5))
    after = classify(actions=(approved,), cutoff=date(2027, 4, 15))
    assert before.counted == ()
    assert [(row.action_id, row.effective_date) for row in after.counted] == [
        ("add", date(2027, 3, 31))
    ]
    assert after.board_adjusted_total_change == 1
    assert after.counted[0].approved_date == date(2027, 4, 10)


def test_recorded_date_takes_precedence_over_earlier_observation():
    late = CandidateLifecycleEvent(
        "one", "joined", (SourceReference("invented", "late"),),
        "Invented event", effective_date=START,
        observed_date=START, recorded_date=date(2027, 4, 10),
    )
    records = (*snapshot("one", "FACT", date(2026, 12, 31)), late)
    assert classify(records, cutoff=date(2027, 4, 5)).counted == ()
    assert len(classify(records, cutoff=date(2027, 4, 10)).counted) == 1


def test_evidence_correction_waits_for_its_replacement_record():
    records = (
        *snapshot("one", "FACT", date(2026, 12, 31)),
        event("one", "joined", START),
        event("one", "joined", START, date(2027, 4, 10)),
    )
    ledger = build_member_evidence_ledger(records)
    joins = [entry for entry in ledger.entries if isinstance(entry.record, CandidateLifecycleEvent)]
    old = next(entry for entry in joins if entry.record.recorded_date == START)
    replacement = next(entry for entry in joins if entry.record.recorded_date != START)
    correction = EvidenceCorrection(
        "one", old.record_id, replacement.record_id,
        (SourceReference("invented-review", "1"),), "Revised source",
        recorded_date=date(2027, 4, 5),
    )
    def run(cutoff):
        return classify_quarterly_movements(
            ledger.entries, START, END, cutoff, RULES,
            BoardPendingActions((), ()), ("A",), (correction,),
        )

    early = run(date(2027, 4, 5))
    late = run(date(2027, 4, 10))
    assert early.applied_corrections == ()
    assert early.counted[0].recorded_date == START
    assert late.applied_corrections == (correction,)
    assert late.counted[0].recorded_date == date(2027, 4, 10)


def test_m3_mapping_and_rejected_withdrawn_reasons():
    records = (
        *snapshot("one", "FACT", date(2026, 12, 31)),
        event("one", "joined", START, member_type="ASSOC"),
        *snapshot("one", "ASSOC", date(2027, 1, 2)),
    )
    actions = (
        action(
            "reject",
            "other",
            ActionKind.NEW_MEMBER_APPROVAL,
            ActionStatus.REJECTED,
            START,
        ),
        action(
            "withdraw",
            "third",
            ActionKind.NEW_MEMBER_APPROVAL,
            ActionStatus.WITHDRAWN,
            START,
        ),
    )
    ledger = build_member_evidence_ledger(records)
    result = classify_quarterly_movements(
        ledger.entries,
        START,
        END,
        date(2027, 4, 15),
        RULES,
        BoardPendingActions(actions, ()),
        ("A",),
        join_measures={"ASSOC": "M3"},
    )
    assert result.counted[0].measure == "M3"
    assert {row.status for row in result.noncounted} == {
        ActionStatus.REJECTED,
        ActionStatus.WITHDRAWN,
    }
    assert all(row.reason for row in result.noncounted)


def test_join_measure_uses_member_type_at_join_before_later_transfer():
    records = (
        *snapshot("one", "FACT", date(2026, 12, 31)),
        event("one", "joined", START, member_type="ACT"),
        *snapshot("one", "ASSOC", date(2027, 2, 1)),
    )
    ledger = build_member_evidence_ledger(records)
    result = classify_quarterly_movements(
        ledger.entries,
        START,
        END,
        date(2027, 4, 15),
        RULES,
        BoardPendingActions((), ()),
        ("A",),
        join_measures={"ASSOC": "M3"},
    )
    assert [(row.action, row.measure) for row in result.counted] == [("joined", "M2")]
    assert result.movement.contributors[0].dated_actions[0].member_type == "ACT"
    assert result.movement.contributors[0].closing_member_type == "ASSOC"
