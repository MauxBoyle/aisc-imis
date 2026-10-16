"""M1 examples use invented member evidence and Board actions."""

import csv
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from aisc_imis.board_adjusted_membership import build_board_adjusted_membership
from aisc_imis.board_pending_actions import (
    ActionKind,
    ActionRevision,
    ActionStatus,
    BoardAction,
    BoardPendingActions,
)
from aisc_imis.evidence_ledger import CandidateLifecycleEvent, SnapshotStateObservation
from aisc_imis.lifecycle_rules import load_lifecycle_rules
from aisc_imis.m1_membership_numbers import build_m1_membership_numbers, write_m1_csv
from aisc_imis.member_ledger import build_member_evidence_ledger
from aisc_imis.normalization_contracts import SourceReference
from aisc_imis.operational_membership_summary import summarize_operational_membership
from aisc_imis.period_membership_balance import (
    ReviewedBalanceAdjustment,
    reconcile_membership_balance,
)

START, END, CUTOFF = date(2027, 1, 1), date(2027, 4, 1), date(2027, 4, 15)
RULES = load_lifecycle_rules(Path(__file__).parents[1] / "data/reference")


def snapshot(key, member_type, category, when):
    return tuple(
        SnapshotStateObservation(
            key,
            f"{field}={value}",
            SourceReference("invented", key),
            effective_date=when,
            recorded_date=when,
        )
        for field, value in (
            ("member_type", member_type),
            ("category", category),
            ("is_member", True),
            ("is_company", False),
        )
    )


def event(key, name, when, category=None, recorded=None):
    return CandidateLifecycleEvent(
        key,
        name,
        (SourceReference("invented", key),),
        "Invented event",
        category=category,
        effective_date=when,
        recorded_date=recorded or when,
    )


def board_action(key, category, approved, effective):
    revision = ActionRevision(
        f"add-{key}",
        f"add-{key}-1",
        None,
        key,
        ActionKind.NEW_MEMBER_APPROVAL,
        ActionStatus.APPROVED,
        approved,
        "Invented secretary",
        "Invented reason",
        "minutes/p1",
        effective_date=effective,
        desired_category=category,
        member_type="ACT",
    )
    return BoardAction(
        revision.action_id, key, ActionKind.NEW_MEMBER_APPROVAL, (revision,)
    )


def build(records=(), actions=(), adjustments=(), cutoff=CUTOFF):
    entries = build_member_evidence_ledger(records).entries
    categories = ("A", "B")
    balance = reconcile_membership_balance(
        entries,
        START,
        END,
        categories,
        RULES,
        adjustments=adjustments,
        knowledge_cutoff=cutoff,
    )
    opening_day = START - timedelta(days=1)
    closing_day = END - timedelta(days=1)
    pending = BoardPendingActions(tuple(actions), ())
    opening = build_board_adjusted_membership(
        summarize_operational_membership(
            entries,
            opening_day,
            opening_day - timedelta(days=1),
            categories,
            RULES,
            knowledge_cutoff=cutoff,
        ),
        pending,
        cutoff,
    )
    closing = build_board_adjusted_membership(
        summarize_operational_membership(
            entries,
            closing_day,
            opening_day,
            categories,
            RULES,
            knowledge_cutoff=cutoff,
        ),
        pending,
        cutoff,
    )
    return build_m1_membership_numbers(balance, opening, closing, cutoff)


def test_overall_categories_transfers_board_actions_and_reviewed_difference(tmp_path):
    records = (
        *snapshot("move", "ACT", "A", START - timedelta(days=1)),
        *snapshot("move", "ACT", "B", START),
        *snapshot("join", "FACT", "A", START - timedelta(days=1)),
        event("join", "joined", START, "A"),
    )
    reviewed = ReviewedBalanceAdjustment(
        "move",
        START,
        "A",
        1,
        "Reviewed change",
        (SourceReference("review", "1"),),
    )
    result = build(
        records, (board_action("new", "B", date(2027, 4, 5), START),), (reviewed,)
    )
    overall, a, b = result.overall, result.categories["A"], result.categories["B"]
    assert (
        overall.operational_opening,
        overall.joined,
        overall.operational_closing,
    ) == (1, 1, 2)
    assert (a.transfers_out, b.transfers_in) == (1, 1)
    assert (a.reviewed_adjustments, overall.reviewed_adjustments) == (1, 1)
    assert (overall.board_opening_adjustment, overall.board_closing_adjustment) == (
        0,
        1,
    )
    assert (overall.board_adjusted_opening, overall.board_adjusted_closing) == (1, 3)
    assert (overall.operational_difference, overall.board_adjusted_difference) == (
        -1,
        -1,
    )
    assert overall.status == "unresolved_difference"
    assert result.operational_as_of_date == date(2027, 3, 31)
    assert result.board_cutoff == CUTOFF
    path = tmp_path / "m1.csv"
    write_m1_csv(result, path)
    with path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 3
    assert rows[0]["category"] == ""
    assert rows[0]["operational_difference"] == "-1"
    assert rows[0]["board_adjusted_difference"] == "-1"
    assert rows[0]["status"] == "unresolved_difference"
    assert rows[2]["category"] == "B"


def test_unknown_totals_stay_blank_while_confirmed_movements_remain(tmp_path):
    records = (
        *snapshot("unknown", "ACT", "A", START),
        *snapshot("known", "FACT", "B", START - timedelta(days=1)),
        event("known", "joined", START, "B"),
    )
    result = build(records)
    assert result.overall.joined == 1
    assert result.overall.operational_opening is None
    assert result.overall.board_adjusted_closing is None
    assert result.overall.operational_difference is None
    assert result.overall.status == "unresolved_unknown"
    path = tmp_path / "unknown.csv"
    write_m1_csv(result, path)
    with path.open(newline="", encoding="utf-8") as file:
        row = next(csv.DictReader(file))
    assert row["operational_opening"] == ""
    assert row["board_adjusted_difference"] == ""
    assert row["joined"] == "1"
    assert row["status"] == "unresolved_unknown"


def test_reconciled_row_has_period_dates_and_zero_differences():
    result = build(snapshot("steady", "ACT", "A", START - timedelta(days=1)))
    assert result.overall.status == "reconciled"
    assert result.overall.start_date == START
    assert result.overall.end_date == END
    assert result.overall.operational_as_of_date == END - timedelta(days=1)
    assert result.overall.board_cutoff == CUTOFF
    assert result.overall.operational_difference == 0
    assert result.overall.board_adjusted_difference == 0


def test_unassigned_board_category_keeps_category_totals_unknown():
    result = build(
        snapshot("steady", "ACT", "A", START - timedelta(days=1)),
        (board_action("new", None, date(2027, 4, 5), START),),
    )
    assert result.overall.board_adjusted_closing == 2
    assert result.categories["A"].board_adjusted_closing is None
    assert result.categories["A"].status == "unresolved_unknown"


def test_cutoffs_and_inconsistent_inputs_are_rejected():
    records = (
        *snapshot("m", "FACT", "A", START - timedelta(days=1)),
        event("m", "joined", END, "A"),
    )
    assert build(records).overall.joined == 0
    late_board = board_action("new", "B", date(2027, 4, 16), START)
    assert build(records, (late_board,)).overall.board_closing_adjustment == 0
    with pytest.raises(ValueError):
        build(records, cutoff=date(2027, 3, 30))

    entries = build_member_evidence_ledger(records).entries
    balance = reconcile_membership_balance(entries, START, END, ("A", "B"), RULES)
    pending = BoardPendingActions((), ())
    opening = build_board_adjusted_membership(
        summarize_operational_membership(
            entries,
            START - timedelta(days=1),
            START - timedelta(days=2),
            ("A", "B"),
            RULES,
            knowledge_cutoff=CUTOFF,
        ),
        pending,
        CUTOFF,
    )
    closing = build_board_adjusted_membership(
        summarize_operational_membership(
            entries,
            END - timedelta(days=1),
            START - timedelta(days=1),
            ("A", "B"),
            RULES,
            knowledge_cutoff=CUTOFF,
        ),
        pending,
        CUTOFF,
    )
    with pytest.raises(ValueError):
        build_m1_membership_numbers(
            balance, opening, replace(closing, board_cutoff=END), CUTOFF
        )
