"""Tests for evidence-preserving membership lifecycle reconstruction."""

from datetime import date
from pathlib import Path

import pytest

from aisc_imis.evidence_ledger import (
    CandidateLifecycleEvent,
    InterpretationStatus,
    SnapshotStateObservation,
)
from aisc_imis.lifecycle_reconstruction import (
    UNKNOWN_BEFORE_COVERAGE,
    LifecycleState,
    reconstruct_member_lifecycle,
)
from aisc_imis.lifecycle_rules import load_lifecycle_rules
from aisc_imis.member_ledger import build_member_evidence_ledger
from aisc_imis.normalization_contracts import SourceReference

REFERENCE_DIRECTORY = Path(__file__).parents[1] / "data" / "reference"


def event(name, effective, recorded=None, *, status=InterpretationStatus.INFERRED):
    return CandidateLifecycleEvent(
        subject_key="member-1",
        event_name=name,
        source_references=(SourceReference("events.csv", name),),
        interpretation_reason="synthetic reviewed event",
        effective_date=effective,
        recorded_date=recorded or effective,
        interpretation_status=status,
    )


def snapshot(field, value, observed, *, row="snapshot-1", recorded=None):
    return SnapshotStateObservation(
        subject_key="member-1",
        state_name=f"{field}={value}",
        source_reference=SourceReference("snapshot.csv", row),
        observed_date=observed,
        recorded_date=recorded or observed,
    )


@pytest.fixture
def rules():
    return load_lifecycle_rules(REFERENCE_DIRECTORY)


def reconstruct(records, as_of, rules):
    return reconstruct_member_lifecycle(
        build_member_evidence_ledger(records).entries_for("member-1"), as_of, rules
    )


@pytest.mark.parametrize(
    ("events", "expected"),
    [
        ((event("joined", date(2026, 10, 15)),), LifecycleState.CURRENT_MEMBER),
        (
            (
                event("joined", date(2026, 10, 15)),
                event("resigned", date(2026, 10, 16)),
                event("reinstated", date(2026, 10, 17)),
            ),
            LifecycleState.CURRENT_MEMBER,
        ),
    ],
)
def test_reconstructs_reviewed_event_target_states(rules, events, expected):
    result = reconstruct(events, date(2026, 10, 17), rules)

    assert result.state is expected
    assert result.intervals[-1].end_date is None
    assert result.supporting_evidence


def test_snapshot_state_carries_forward_and_never_backfills_before_coverage(rules):
    records = (
        snapshot("member_type", "ACT", date(2026, 10, 15)),
        snapshot("is_member", "True", date(2026, 10, 15)),
        snapshot("is_company", "True", date(2026, 10, 15)),
    )

    before = reconstruct(records, date(2026, 10, 14), rules)
    after = reconstruct(records, date(2026, 10, 20), rules)

    assert before.state is LifecycleState.UNKNOWN
    assert before.intervals == ()
    assert after.state is LifecycleState.CURRENT_MEMBER
    assert after.opening_strategy is UNKNOWN_BEFORE_COVERAGE
    assert after.intervals[0].start_date == date(2026, 10, 15)


def test_same_day_conflicts_are_retained_and_make_the_period_unknown(rules):
    result = reconstruct(
        (event("joined", date(2026, 10, 15)), event("resigned", date(2026, 10, 15))),
        date(2026, 10, 15),
        rules,
    )

    assert result.state is LifecycleState.UNKNOWN
    assert len(result.supporting_evidence) == 2
    assert any(finding.code == "same_day_state_contradiction" for finding in result.findings)


def test_missing_dates_and_unresolved_evidence_are_unknown_findings(rules):
    missing = event("joined", None, date(2026, 10, 15))
    unresolved = event(
        "joined", date(2026, 10, 16), status=InterpretationStatus.UNRESOLVED
    )

    result = reconstruct((missing, unresolved), date(2026, 10, 16), rules)

    assert result.state is LifecycleState.UNKNOWN
    assert {finding.code for finding in result.findings} >= {
        "missing_lifecycle_date",
        "unresolved_lifecycle_evidence",
    }


def test_missing_rule_and_future_recorded_evidence_do_not_create_state(rules):
    before_rules = reconstruct((event("joined", date(2026, 10, 14)),), date(2026, 10, 14), rules)
    late = reconstruct(
        (event("joined", date(2026, 10, 15), date(2026, 10, 20)),),
        date(2026, 10, 15),
        rules,
    )

    assert before_rules.state is LifecycleState.CURRENT_MEMBER
    assert late.state is LifecycleState.UNKNOWN
    assert late.supporting_evidence == ()
