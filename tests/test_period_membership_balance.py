"""Synthetic examples of the membership balance equation."""

from datetime import date
from pathlib import Path

import pytest

from aisc_imis.evidence_ledger import CandidateLifecycleEvent, SnapshotStateObservation
from aisc_imis.lifecycle_period_movements import EvidenceCorrection
from aisc_imis.lifecycle_rules import load_lifecycle_rules
from aisc_imis.member_ledger import build_member_evidence_ledger
from aisc_imis.normalization_contracts import SourceReference
from aisc_imis.period_membership_balance import (
    ReviewedBalanceAdjustment,
    reconcile_membership_balance,
)

RULES = load_lifecycle_rules(Path(__file__).parents[1] / "data" / "reference")
START = date(2026, 10, 16)
END = date(2026, 10, 20)


def snapshot(member, member_type, category, when, row):
    fields = (("member_type", member_type), ("is_member", True), ("is_company", False))
    if category is not None:
        fields = (*fields, ("category", category))
    return tuple(
        SnapshotStateObservation(member, f"{field}={value}", SourceReference("synthetic", row), observed_date=when, recorded_date=when)
        for field, value in fields
    )


def event(member, name, when, row, category=None):
    return CandidateLifecycleEvent(member, name, (SourceReference("synthetic", row),), "synthetic", category=category, effective_date=when, recorded_date=when)


def balance(records, *, corrections=(), adjustments=(), categories=("A", "B")):
    entries = build_member_evidence_ledger(records).entries
    return reconcile_membership_balance(entries, START, END, categories, RULES, corrections, adjustments)


@pytest.mark.parametrize(
    ("records", "expected_opening", "expected_actions", "expected_closing"),
    [
        (snapshot("m", "ACT", "A", date(2026, 10, 15), "open"), 1, {}, 1),
        ((*snapshot("m", "FACT", "A", date(2026, 10, 15), "open"), event("m", "joined", START, "join", "A")), 0, {"joined": 1}, 1),
        ((*snapshot("m", "FACT", "A", date(2026, 10, 15), "open"), event("m", "joined", START, "join", "A"), event("m", "resigned", date(2026, 10, 17), "exit")), 0, {"joined": 1, "resigned": 1}, 0),
    ],
)
def test_balanced_lifecycle_cases(records, expected_opening, expected_actions, expected_closing):
    result = balance(records)
    assert result.overall.opening == expected_opening
    assert result.overall.movements == {name: expected_actions.get(name, 0) for name in ("joined", "reinstated", "resigned", "expelled", "exited")}
    assert result.overall.closing == expected_closing
    assert result.overall.difference == 0
    assert result.overall.complete
    assert result.overall.terms["opening"] or expected_opening == 0


def test_category_transfer_has_zero_overall_effect_and_two_category_lines():
    records = (*snapshot("m", "ACT", "A", date(2026, 10, 15), "open"), *snapshot("m", "ACT", "B", START, "transfer"))
    result = balance(records)
    assert result.overall.difference == 0
    assert result.categories["A"].transfers_out == 1
    assert result.categories["A"].closing == 0
    assert result.categories["B"].transfers_in == 1
    assert result.categories["B"].closing == 1
    assert result.categories["A"].terms["transfers_out"][0].subject_key == "m"


def test_correction_changes_opening_without_creating_adjustment():
    records = (*snapshot("m", "FACT", "A", date(2026, 10, 15), "wrong"), *snapshot("m", "ACT", "A", date(2026, 10, 15), "right"))
    ledger = build_member_evidence_ledger(records)
    wrong = next(x for x in ledger.entries if x.record.state_name == "member_type=FACT")
    right = next(x for x in ledger.entries if x.record.state_name == "member_type=ACT")
    correction = EvidenceCorrection("m", wrong.record_id, right.record_id, (SourceReference("review", "1"),), "wrong type")
    result = reconcile_membership_balance(ledger.entries, START, END, ("A",), RULES, (correction,))
    assert result.overall.opening == 1
    assert result.overall.adjustments == 0
    assert result.overall.difference == 0


def test_reviewed_adjustment_is_explicit_and_retains_its_sources():
    adjustment = ReviewedBalanceAdjustment("m", START, "A", 1, "reviewed count change", (SourceReference("review", "2"),))
    result = balance(snapshot("m", "ACT", "A", date(2026, 10, 15), "open"), adjustments=(adjustment,))
    assert result.overall.adjustments == 1
    assert result.overall.difference == -1
    assert result.categories["A"].terms["adjustments"][0].source_references == adjustment.source_references
    assert "balance_difference" in {finding.code for finding in result.findings}


def test_unclassified_snapshot_join_is_exposed_as_difference():
    records = (*snapshot("m", "FACT", "A", date(2026, 10, 15), "open"), *snapshot("m", "ACT", "A", START, "new"))
    result = balance(records)
    assert result.overall.difference == 1
    assert "unclassified_movement" in {finding.code for finding in result.findings}


def test_unknown_countability_suppresses_overall_difference():
    result = balance(snapshot("m", "ACT", "A", START, "first"))
    assert not result.overall.complete
    assert result.overall.opening is None
    assert result.overall.difference is None


def test_unknown_member_keeps_other_confirmed_movements_visible():
    records = (
        *snapshot("known", "FACT", "A", date(2026, 10, 15), "known-open"),
        event("known", "joined", START, "known-join", "A"),
        *snapshot("unknown", "ACT", "A", START, "unknown-open"),
    )
    result = balance(records)
    assert result.overall.movements["joined"] == 1
    assert result.overall.difference is None
    assert result.overall.terms["joined"][0].subject_key == "known"


def test_unknown_category_keeps_overall_complete_but_category_incomplete():
    result = balance(snapshot("m", "ACT", None, date(2026, 10, 15), "open"))
    assert result.overall.difference == 0
    assert result.categories["A"].difference is None
    assert "unknown_category" in {finding.code for finding in result.findings}


def test_unresolved_snapshot_does_not_create_a_false_zero_difference():
    records = (
        *snapshot("m", "ACT", "A", date(2026, 10, 15), "open"),
        SnapshotStateObservation("m", "member_type=UNKNOWN", SourceReference("synthetic", "bad"), observed_date=START, recorded_date=START),
        SnapshotStateObservation("m", "is_member=True", SourceReference("synthetic", "bad"), observed_date=START, recorded_date=START),
        SnapshotStateObservation("m", "is_company=False", SourceReference("synthetic", "bad"), observed_date=START, recorded_date=START),
    )
    result = balance(records)
    assert result.overall.difference is None
    assert "unresolved_lifecycle_evidence" in {finding.code for finding in result.findings}


def test_end_date_event_is_excluded():
    records = (*snapshot("m", "FACT", "A", date(2026, 10, 15), "open"), event("m", "joined", END, "late", "A"))
    result = balance(records)
    assert all(count == 0 for count in result.overall.movements.values())
    assert result.overall.difference == 0


def test_adjustment_requires_audit_fields():
    with pytest.raises(ValueError):
        ReviewedBalanceAdjustment("m", START, "A", 1, "", (SourceReference("review", "2"),))
