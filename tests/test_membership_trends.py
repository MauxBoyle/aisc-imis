"""Synthetic, source-backed acceptance cases for membership trends."""

from datetime import date, datetime
from pathlib import Path

import pytest

from aisc_imis.evidence_ledger import CandidateLifecycleEvent, SnapshotStateObservation
from aisc_imis.lifecycle_period_movements import EvidenceCorrection
from aisc_imis.lifecycle_rules import load_lifecycle_rules
from aisc_imis.member_ledger import build_member_evidence_ledger
from aisc_imis.membership_trends import build_membership_trends
from aisc_imis.normalization_contracts import SourceReference

RULES = load_lifecycle_rules(Path(__file__).parents[1] / "data" / "reference")
BASE = date(2026, 10, 15)
MIDDLE = date(2026, 10, 20)
END = date(2026, 10, 25)


def snapshot(member, member_type, category, when, row):
    fields = (("member_type", member_type), ("is_member", True), ("is_company", False))
    if category is not None:
        fields = (*fields, ("category", category))
    return tuple(
        SnapshotStateObservation(
            member, f"{field}={value}", SourceReference("synthetic", row),
            observed_date=when, recorded_date=when,
        )
        for field, value in fields
    )


def event(member, name, when, row, *, category=None, member_type=None):
    return CandidateLifecycleEvent(
        member, name, (SourceReference("synthetic", row),), "synthetic",
        category=category, member_type=member_type,
        effective_date=when, recorded_date=when,
    )


def trends(records, dates=(BASE, MIDDLE), corrections=()):
    entries = build_member_evidence_ledger(records).entries
    return build_membership_trends(entries, dates, ("A", "B"), RULES, corrections)


def test_consecutive_periods_retain_summary_and_count_proofs():
    records = (
        *snapshot("steady", "ACT", "A", BASE, "steady"),
        *snapshot("new", "FACT", "B", BASE, "new-open"),
        event("new", "joined", MIDDLE, "new-join", category="B", member_type="ACT"),
        event("steady", "resigned", END, "steady-exit", category="A"),
    )
    result = trends(records, (BASE, MIDDLE, END))
    assert len(result.periods) == 2
    first, second = result.periods
    assert (first.prior_as_of_date, first.as_of_date) == (BASE, MIDDLE)
    assert (second.prior_as_of_date, second.as_of_date) == (MIDDLE, END)
    assert first.overall.opening_count == first.summary.balance.overall.opening == 1
    assert first.overall.closing_confirmed_count == first.summary.overall.confirmed_count == 2
    assert first.overall.closing_count == first.summary.overall.total == 2
    assert first.overall.movements["joined"] == 1
    assert first.overall.net_change == 1
    assert second.overall.opening_count == 2
    assert second.overall.closing_count == 1
    assert second.overall.movements["resigned"] == 1
    assert second.overall.net_change == -1
    assert second.overall.difference == 0
    assert {decision.subject_key for decision in first.decisions} == {"steady", "new"}
    new = next(item for item in first.decisions if item.subject_key == "new")
    assert new.opening_status == "excluded"
    assert new.closing_status == "included"
    assert new.closing_member_type == "ACT"
    assert len(new.terms["joined"]) == 1
    assert SourceReference("synthetic", "new-join") in new.source_references


def test_category_transfer_changes_categories_without_changing_overall():
    result = trends((*snapshot("m", "ACT", "A", BASE, "open"), *snapshot("m", "ACT", "B", MIDDLE, "move")))
    period = result.periods[0]
    assert period.overall.opening_count == period.overall.closing_count == 1
    assert period.overall.net_change == 0
    assert period.categories["A"].transfers_out == 1
    assert period.categories["B"].transfers_in == 1
    assert period.categories["A"].closing_count == 0
    assert period.categories["B"].closing_count == 1
    assert len(period.decisions[0].category_transfers) == 1
    assert period.decisions[0].opening_category == "A"
    assert period.decisions[0].closing_category == "B"


@pytest.mark.parametrize(
    ("records", "expected_action", "expected_change"),
    [
        ((*snapshot("m", "FACT", "A", BASE, "open"), event("m", "joined", MIDDLE, "event", category="A")), "joined", 1),
        ((*snapshot("m", "ACT", "A", BASE, "open"), event("m", "resigned", MIDDLE, "event", category="A")), "resigned", -1),
    ],
)
def test_lifecycle_movement_is_traceable(records, expected_action, expected_change):
    period = trends(records).periods[0]
    assert period.overall.movements[expected_action] == 1
    assert period.overall.net_change == expected_change
    assert len(period.decisions[0].terms[expected_action]) == 1


def test_uncertainty_preserves_confirmed_count_and_omits_definitive_numbers():
    records = (*snapshot("known", "ACT", "A", BASE, "known"), *snapshot("uncertain", "ACT", "B", MIDDLE, "late"))
    period = trends(records).periods[0]
    assert period.overall.closing_confirmed_count == 2
    assert period.overall.closing_count is None
    assert period.overall.opening_count is None
    assert period.overall.net_change is None
    assert period.overall.difference is None
    assert period.categories["A"].closing_count is None
    uncertain = next(item for item in period.decisions if item.subject_key == "uncertain")
    assert uncertain.opening_status == "uncertain"
    assert uncertain.closing_status == "included"
    assert uncertain.findings
    assert SourceReference("synthetic", "late") in uncertain.source_references


def test_missing_category_leaves_category_totals_unknown_but_overall_known():
    period = trends(snapshot("m", "ACT", None, BASE, "missing")).periods[0]
    assert period.overall.closing_count == 1
    assert period.categories["A"].closing_confirmed_count == 0
    assert period.categories["A"].closing_count is None
    assert period.categories["B"].closing_count is None
    assert period.decisions[0].closing_status == "included"
    assert period.decisions[0].closing_category is None
    assert any(finding.code == "unknown_category" for finding in period.decisions[0].findings)


def test_correction_and_unexplained_difference_remain_visible():
    records = (
        *snapshot("m", "FACT", "A", BASE, "open"),
        event("m", "joined", MIDDLE, "wrong", category="B"),
        event("m", "joined", MIDDLE, "right", category="A"),
        *snapshot("n", "FACT", "B", BASE, "n-open"),
        *snapshot("n", "ACT", "B", MIDDLE, "n-close"),
    )
    entries = build_member_evidence_ledger(records).entries
    wrong = next(item for item in entries if isinstance(item.record, CandidateLifecycleEvent) and item.record.source_references[0].row_reference == "wrong")
    right = next(item for item in entries if isinstance(item.record, CandidateLifecycleEvent) and item.record.source_references[0].row_reference == "right")
    correction = EvidenceCorrection("m", wrong.record_id, right.record_id, (SourceReference("review", "1"),), "reviewed")
    period = build_membership_trends(entries, (BASE, MIDDLE), ("A", "B"), RULES, (correction,)).periods[0]
    assert period.overall.difference == 1
    assert period.overall.movements["joined"] == 1
    assert period.overall.net_change == 2
    assert period.categories["B"].difference == 1
    assert any(finding.code == "balance_difference" for finding in period.findings)
    corrected = next(item for item in period.decisions if item.subject_key == "m")
    assert corrected.applied_corrections == (correction,)
    assert SourceReference("review", "1") in corrected.source_references
    assert SourceReference("synthetic", "wrong") not in corrected.source_references
    assert any(finding.code == "unclassified_movement" for finding in period.decisions[1].findings)


@pytest.mark.parametrize(
    "dates", [(), (BASE,), (BASE, BASE), (MIDDLE, BASE), (BASE, datetime(2026, 10, 20))]
)
def test_invalid_date_sequences_are_rejected(dates):
    with pytest.raises(ValueError):
        trends((), dates)
