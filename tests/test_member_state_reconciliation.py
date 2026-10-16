"""Synthetic comparisons of observed membership with independent history."""

from dataclasses import replace
from datetime import date

import pytest

from aisc_imis.evidence_ledger import (
    CandidateLifecycleEvent,
    InterpretationStatus,
    SnapshotStateObservation,
)
from aisc_imis.lifecycle_rules import load_lifecycle_rules
from aisc_imis.member_ledger import build_member_evidence_ledger
from aisc_imis.member_state_reconciliation import (
    MembershipObservation,
    reconcile_member_states,
)
from aisc_imis.normalization_contracts import SourceReference

RULES = load_lifecycle_rules("data/reference")
D1 = date(2026, 10, 16)
D2 = date(2026, 10, 20)


def obs(row, when, *, member_type="ACT", status="A", is_member=True):
    return MembershipObservation(
        subject_key="synthetic-1",
        source_reference=SourceReference("synthetic.csv", row),
        observation_date=when,
        member_type=member_type,
        status=status,
        is_company=True,
        is_member=is_member,
    )


def event(row, when, name="resigned", member_type=None):
    return CandidateLifecycleEvent(
        subject_key="synthetic-1",
        event_name=name,
        source_references=(SourceReference("events.csv", row),),
        interpretation_reason="Synthetic reviewed event",
        effective_date=when,
        recorded_date=when,
        member_type=member_type,
        interpretation_status=InterpretationStatus.VERIFIED,
    )


def run(history, current=(), evidence=()):
    return reconcile_member_states(
        build_member_evidence_ledger(evidence),
        history,
        current,
        RULES,
        current_export_date=D2,
    )


@pytest.mark.parametrize(
    ("target", "expected_outcome", "expected_codes"),
    [
        (obs("target", D2), "match", set()),
        (obs("target", D2, status="S"), "discrepancy", {"possible_missing_transition"}),
        (
            obs("target", D2, member_type="FACT"),
            "discrepancy",
            {"possible_missing_transition", "countability_difference"},
        ),
    ],
)
def test_comparison_scenarios(target, expected_outcome, expected_codes):
    result = run((obs("opening", D1),), (target,))
    comparison = result.comparisons[-1]
    assert comparison.outcome == expected_outcome
    target_findings = [
        finding
        for finding in result.findings
        if target.source_reference in finding.sources
    ]
    assert {finding.code for finding in target_findings} == expected_codes
    for finding in target_findings:
        assert target.source_reference in finding.sources
        assert obs("opening", D1).source_reference in finding.sources


def test_no_earlier_history_is_unassessable_and_cites_target():
    target = obs("only", D2)
    result = run((), (target,))
    assert result.comparisons[0].outcome == "unassessable"
    assert {finding.code for finding in result.findings} == {"unknown_starting_state"}
    assert result.findings[0].sources == (target.source_reference,)


def test_undated_historical_row_is_unassessable_with_source_link():
    target = obs("undated", None)
    result = run((target,))
    assert result.comparisons[0].outcome == "unassessable"
    assert result.findings[0].code == "missing_lifecycle_date"
    assert result.findings[0].sources == (target.source_reference,)


def test_empty_row_still_has_source_link():
    target = MembershipObservation(
        "synthetic-1", SourceReference("synthetic.csv", "empty")
    )
    result = run((target,))
    assert result.findings[0].sources == (target.source_reference,)


def test_same_day_rows_are_not_used_as_each_others_baseline():
    result = run((obs("one", D1), obs("two", D1, member_type="FACT")))
    assert all(item.outcome == "unassessable" for item in result.comparisons)
    assert "snapshot_state_conflict" in {item.code for item in result.findings}
    assert {
        source.row_reference for item in result.findings for source in item.sources
    } == {"one", "two"}


def test_pre_rule_snapshot_has_no_rule_based_countability():
    before = date(2025, 6, 25)
    result = run(
        (obs("earlier", date(2025, 6, 5)), obs("target", before, is_member=False))
    )
    target = next(
        item
        for item in result.comparisons
        if item.observation.source_reference.row_reference == "target"
    )
    assert target.expected_countability is None
    assert target.observed_countability is None
    assert "countability_difference" not in {
        finding.code for finding in result.findings
    }


def test_current_export_date_is_explicit_and_missing_fields_stay_unassessable():
    target = obs("target", date(2025, 1, 1), member_type=None, status=None)
    result = run((obs("opening", D1),), (target,))
    comparison = result.comparisons[-1]
    assert comparison.comparison_date == D2
    assert comparison.outcome == "unassessable"


def test_relevant_event_can_explain_state_change():
    result = run(
        (obs("opening", D1),),
        (obs("target", D2, member_type="FACT"),),
        (event("resigned", date(2026, 10, 18), member_type="FACT"),),
    )
    assert result.comparisons[-1].outcome == "match"
    assert not [
        finding
        for finding in result.findings
        if finding.scope.startswith(D2.isoformat())
    ]


def test_countability_difference_after_reviewed_event():
    target = obs("target", D2)
    result = run(
        (obs("opening", D1),), (target,), (event("resigned", date(2026, 10, 18)),)
    )
    assert result.comparisons[-1].outcome == "discrepancy"
    finding = next(
        item for item in result.findings if item.code == "countability_difference"
    )
    assert {source.row_reference for source in finding.sources} == {
        "resigned",
        "target",
    }


def test_reviewed_event_on_comparison_date_is_available():
    result = run(
        (obs("opening", D1),),
        (obs("target", D2, member_type="FACT"),),
        (event("resigned", D2, member_type="FACT"),),
    )
    assert result.comparisons[-1].outcome == "match"


def test_status_only_snapshot_preserves_reviewed_countability_transition():
    partial = replace(
        obs("status_only", date(2026, 10, 19), status="S"),
        member_type=None,
        is_company=None,
        is_member=None,
    )
    result = run(
        (obs("opening", D1), partial),
        (obs("target", D2, status="S"),),
        (event("resigned", date(2026, 10, 18)),),
    )
    comparison = result.comparisons[-1]
    assert comparison.outcome == "discrepancy"
    assert comparison.expected_countability == "not_countable"
    finding = next(
        item for item in result.findings if item.code == "countability_difference"
    )
    assert {source.row_reference for source in finding.sources} == {
        "resigned",
        "target",
    }


def test_partial_countability_snapshot_preserves_earlier_event():
    partial = replace(
        obs("partial", date(2026, 10, 19), member_type="FACT"),
        is_company=None,
        is_member=None,
    )
    result = run(
        (obs("opening", D1), partial),
        (obs("target", D2, member_type="FACT"),),
        (event("resigned", date(2026, 10, 18)),),
    )
    comparison = result.comparisons[-1]
    assert comparison.expected_countability == "not_countable"
    assert comparison.outcome == "match"
    assert "unassessable_countability_snapshot" not in {
        item.code for item in result.findings
    }


def test_late_recorded_snapshot_does_not_change_earlier_comparison():
    late = SnapshotStateObservation(
        "synthetic-1",
        "status=S",
        SourceReference("late.csv", "one"),
        effective_date=date(2026, 10, 17),
        recorded_date=date(2026, 10, 21),
    )
    result = run((obs("opening", D1),), (obs("target", D2),), (late,))
    comparison = result.comparisons[-1]
    assert comparison.expected_status == "A"
    assert comparison.outcome == "match"


def test_late_recorded_event_does_not_change_earlier_comparison():
    late = replace(event("late", date(2026, 10, 18)), recorded_date=date(2026, 10, 21))
    result = run((obs("opening", D1),), (obs("target", D2),), (late,))
    assert result.comparisons[-1].expected_countability == "countable"
    assert result.comparisons[-1].outcome == "match"


def test_partial_snapshot_carries_earlier_fields_forward():
    partial = replace(
        obs("partial", date(2026, 10, 19), status="S"),
        member_type=None,
        is_company=None,
        is_member=None,
    )
    result = run((obs("opening", D1), partial), (obs("target", D2, status="S"),))
    comparison = result.comparisons[-1]
    assert comparison.expected_member_type == "ACT"
    assert comparison.expected_countability == "countable"
    assert comparison.outcome == "match"


def test_conflicting_same_day_events_leave_countability_unknown_with_finding():
    result = run(
        (obs("opening", D1),),
        (obs("target", D2),),
        (
            event("resigned", date(2026, 10, 18)),
            event("joined", date(2026, 10, 18), name="joined"),
        ),
    )
    comparison = result.comparisons[-1]
    assert comparison.expected_countability is None
    assert comparison.outcome == "unassessable"
    finding = next(
        item for item in result.findings if item.code == "same_day_state_contradiction"
    )
    assert {source.row_reference for source in finding.sources} == {
        "resigned",
        "joined",
        "target",
    }


def test_missing_supported_field_prevents_match_and_creates_finding():
    opening = replace(obs("opening", D1), status=None)
    target = obs("target", D2)
    result = run((opening,), (target,))
    assert result.comparisons[-1].outcome == "unassessable"
    assert "unassessable_state_field" in {finding.code for finding in result.findings}


def test_complete_snapshot_supersedes_earlier_countability_event():
    result = run(
        (obs("opening", D1), obs("new_state", date(2026, 10, 19))),
        (obs("target", D2),),
        (event("resigned", date(2026, 10, 18)),),
    )
    comparison = result.comparisons[-1]
    assert comparison.expected_countability == "countable"
    assert not [
        finding
        for finding in result.findings
        if finding.scope.startswith(D2.isoformat())
    ]


def test_unresolved_intervening_event_prevents_confident_comparison():
    candidate = replace(
        event("uncertain", date(2026, 10, 18), member_type="FACT"),
        interpretation_status=InterpretationStatus.UNRESOLVED,
    )
    target = obs("target", D2, member_type="FACT")
    result = run((obs("opening", D1),), (target,), (candidate,))
    assert result.comparisons[-1].outcome == "unassessable"
    assert "possible_missing_transition" not in {item.code for item in result.findings}
    finding = next(
        item for item in result.findings if item.code == "unresolved_lifecycle_evidence"
    )
    assert {source.row_reference for source in finding.sources} == {
        "uncertain",
        "target",
    }


def test_findings_are_stable_when_input_order_changes():
    history = (obs("opening", D1), obs("other", D1))
    current = (obs("target", D2, status="S", member_type="FACT"),)
    first = run(history, current)
    second = run(tuple(reversed(history)), current)
    assert first == second


def test_payment_evidence_does_not_replace_prior_state():
    target = obs("target", D2, status="S")
    result = run(
        (obs("opening", D1),),
        (target,),
        (event("payment", date(2026, 10, 18), name="dues"),),
    )
    finding = next(
        item for item in result.findings if item.code == "possible_missing_transition"
    )
    assert {source.row_reference for source in finding.sources} == {"opening", "target"}
