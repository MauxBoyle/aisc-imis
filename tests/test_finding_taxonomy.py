"""Synthetic checks for stable, reviewable reconciliation findings."""

from datetime import date

import pytest

from aisc_imis.evidence_ledger import CandidateLifecycleEvent
from aisc_imis.finding_taxonomy import (
    FindingType,
    ReviewState,
    Severity,
    build_finding,
    order_findings,
)
from aisc_imis.lifecycle_reconstruction import (
    LifecycleState,
    reconstruct_member_lifecycle,
)
from aisc_imis.lifecycle_rules import load_lifecycle_rules
from aisc_imis.member_ledger import build_member_evidence_ledger
from aisc_imis.normalization_contracts import SourceReference


def _entries():
    records = (
        CandidateLifecycleEvent(
            "member-1",
            "joined",
            (SourceReference("events", "a"),),
            "synthetic",
            effective_date=date(2026, 10, 15),
            recorded_date=date(2026, 10, 15),
        ),
        CandidateLifecycleEvent(
            "member-1",
            "resigned",
            (SourceReference("events", "b"),),
            "synthetic",
            effective_date=date(2026, 10, 15),
            recorded_date=date(2026, 10, 15),
        ),
    )
    return build_member_evidence_ledger(records).entries_for("member-1")


@pytest.mark.parametrize(
    ("code", "kind", "severity"),
    [
        ("missing_lifecycle_date", FindingType.INFORMATION_GAP, Severity.INFO),
        ("unknown_starting_state", FindingType.INFORMATION_GAP, Severity.INFO),
        (
            "unresolved_lifecycle_evidence",
            FindingType.UNCERTAIN_INFERENCE,
            Severity.WARNING,
        ),
        ("same_day_state_contradiction", FindingType.EVIDENCE_CONFLICT, Severity.ERROR),
        ("company_dependent_conflict", FindingType.EVIDENCE_CONFLICT, Severity.ERROR),
        ("repeated_lifecycle_event", FindingType.IMPOSSIBLE_TRANSITION, Severity.ERROR),
        ("balance_difference", FindingType.BALANCE_DIFFERENCE, Severity.ERROR),
    ],
)
def test_representative_lifecycle_codes_have_review_rules(code, kind, severity):
    finding = build_finding(code, "member-1", "2026-10", supporting_evidence=_entries())

    assert finding.type is kind
    assert finding.severity is severity
    assert finding.review_state is ReviewState.OPEN
    assert finding.recommended_action
    assert finding.sources == (
        SourceReference("events", "a"),
        SourceReference("events", "b"),
    )


def test_id_ignores_input_order_and_review_metadata_but_tracks_identity():
    first, second = _entries()
    original = build_finding(
        "same_day_state_contradiction",
        "member-1",
        "2026-10-15",
        supporting_evidence=(first,),
        contradicting_evidence=(second,),
    )
    reordered = build_finding(
        "same_day_state_contradiction",
        "member-1",
        "2026-10-15",
        supporting_evidence=(first, first),
        contradicting_evidence=(second,),
        review_state=ReviewState.CONFIRMED,
        severity=Severity.CRITICAL,
    )
    different = build_finding(
        "same_day_state_contradiction",
        "member-1",
        "2026-10-16",
        supporting_evidence=(first,),
        contradicting_evidence=(second,),
    )

    assert original.id == reordered.id
    assert original.id != different.id
    assert original.supporting_evidence_ids == (first.record_id,)
    assert original.contradicting_evidence_ids == (second.record_id,)
    assert original.severity is Severity.ERROR
    assert reordered.severity is Severity.CRITICAL


def test_ordering_is_deterministic_across_input_orders():
    first, second = _entries()
    findings = (
        build_finding("balance_difference", "member-2", "2026-10"),
        build_finding(
            "missing_lifecycle_date",
            "member-1",
            "2026-10",
            supporting_evidence=(first,),
        ),
        build_finding(
            "same_day_state_contradiction",
            "member-1",
            "2026-10",
            supporting_evidence=(first,),
            contradicting_evidence=(second,),
        ),
    )

    assert order_findings(findings) == order_findings(reversed(findings))
    assert [finding.subject_key for finding in order_findings(findings)] == [
        "member-1",
        "member-1",
        "member-2",
    ]


def test_ordering_and_identity_keep_evidence_roles_distinct():
    first, second = _entries()
    supporting = build_finding(
        "same_day_state_contradiction",
        "member-1",
        "2026-10-15",
        supporting_evidence=(first,),
        contradicting_evidence=(second,),
    )
    reversed_roles = build_finding(
        "same_day_state_contradiction",
        "member-1",
        "2026-10-15",
        supporting_evidence=(second,),
        contradicting_evidence=(first,),
    )
    reviewed = build_finding(
        "same_day_state_contradiction",
        "member-1",
        "2026-10-15",
        supporting_evidence=(first,),
        contradicting_evidence=(second,),
        review_state=ReviewState.RESOLVED,
    )

    assert supporting.id != reversed_roles.id
    assert supporting.supporting_sources != supporting.contradicting_sources
    assert order_findings((reviewed, supporting)) == order_findings(
        (supporting, reviewed)
    )


def test_severity_and_review_state_do_not_change_reconstructed_state():
    entries = _entries()
    rules = load_lifecycle_rules("data/reference")
    result = reconstruct_member_lifecycle(entries, date(2026, 10, 15), rules)
    assert result.state is LifecycleState.UNKNOWN

    finding = build_finding(
        "same_day_state_contradiction",
        result.subject_key,
        "2026-10-15",
        supporting_evidence=(entries[0],),
        contradicting_evidence=(entries[1],),
        severity=Severity.INFO,
        review_state=ReviewState.RESOLVED,
    )

    assert finding.severity is Severity.INFO
    assert result.state is LifecycleState.UNKNOWN
    assert result.intervals[-1].state is LifecycleState.UNKNOWN


def test_unknown_code_and_cross_member_evidence_are_rejected():
    first = _entries()[0]
    with pytest.raises(ValueError, match="Unknown finding code"):
        build_finding("made_up", "member-1", "2026-10")
    with pytest.raises(ValueError, match="subject_key"):
        build_finding(
            "missing_lifecycle_date",
            "member-2",
            "2026-10",
            supporting_evidence=(first,),
        )
