"""Tests for reviewed, versioned lifecycle countability rules."""

from datetime import date
from pathlib import Path

import pytest

from aisc_imis.lifecycle_rules import (
    Countability,
    LifecycleObservation,
    evaluate_countability,
    load_lifecycle_rules,
)

REFERENCE_DIRECTORY = Path(__file__).parents[1] / "data" / "reference"


@pytest.fixture
def rules():
    return load_lifecycle_rules(REFERENCE_DIRECTORY)


@pytest.mark.parametrize(
    ("member_type", "is_company"),
    [
        ("ACT", True),
        ("ASSOC", True),
        ("PROF", False),
        ("AFF", True),
        ("STU", False),
        ("EDU", False),
        ("ACTB", True),
        ("ASSCD", False),
        ("PROFD", False),
    ],
)
def test_current_approved_types_are_countable(rules, member_type, is_company):
    decision = evaluate_countability(
        LifecycleObservation(
            member_type=member_type,
            is_company=is_company,
            is_member=True,
            status="S",  # Status is deliberately not a membership decision input.
        ),
        date(2026, 6, 30),
        rules,
    )

    assert decision.rule_version == "2026-06-30"
    assert decision.operational_state == "current_member"
    assert decision.countability is Countability.COUNTABLE
    assert decision.findings == ()


@pytest.mark.parametrize("member_type", ["FACT", "PACT", "FPROD", "PASSC"])
def test_former_and_potential_types_are_not_countable(rules, member_type):
    decision = evaluate_countability(
        LifecycleObservation(member_type=member_type, is_company=False, is_member=True),
        date(2026, 6, 30),
        rules,
    )

    assert decision.countability is Countability.NOT_COUNTABLE
    assert decision.operational_state in {"former_member", "potential_member"}


@pytest.mark.parametrize(
    "observation",
    [
        LifecycleObservation(member_type="ACTD", is_company=True, is_member=True),
        LifecycleObservation(member_type="ACT", is_company=None, is_member=True),
        LifecycleObservation(member_type="ACT", is_company=True, is_member=None),
        LifecycleObservation(member_type="MYSTERY", is_company=True, is_member=True),
    ],
)
def test_unapproved_or_conflicting_state_combinations_are_findings(rules, observation):
    decision = evaluate_countability(observation, date(2026, 6, 30), rules)

    assert decision.countability is Countability.UNKNOWN
    assert decision.findings


@pytest.mark.parametrize(
    ("event_name", "effect", "target_state"),
    [
        ("joined", "increases", "current_member"),
        ("resigned", "decreases", "former_member"),
        ("expelled", "decreases", "former_member"),
        ("reinstated", "increases", "current_member"),
        ("DUES", "evidence_only", "none"),
    ],
)
def test_reviewed_events_have_configured_effects(rules, event_name, effect, target_state):
    decision = evaluate_countability(
        LifecycleObservation(event_name=event_name), date(2026, 6, 30), rules
    )

    assert decision.transition_effect == effect
    assert decision.event_target_state == target_state
    assert decision.findings == ()


def test_unknown_event_is_a_finding(rules):
    decision = evaluate_countability(
        LifecycleObservation(event_name="renewed"), date(2026, 6, 30), rules
    )

    assert decision.countability is Countability.UNKNOWN
    assert decision.findings[0].code == "unsupported_transition"


def test_rule_version_starts_on_its_inclusive_effective_date(rules):
    on_boundary = evaluate_countability(
        LifecycleObservation(member_type="ACT", is_company=True, is_member=True),
        date(2026, 6, 30),
        rules,
    )
    before_boundary = evaluate_countability(
        LifecycleObservation(member_type="ACT", is_company=True, is_member=True),
        date(2026, 6, 29),
        rules,
    )

    assert on_boundary.rule_version == "2026-06-30"
    assert before_boundary.rule_version is None
    assert before_boundary.countability is Countability.UNKNOWN
    assert before_boundary.findings[0].code == "no_applicable_rule_version"


def test_loader_rejects_incomplete_configuration(tmp_path):
    (tmp_path / "lifecycle-rules.csv").write_text("rule_version\n2026-06-30\n")

    with pytest.raises(ValueError, match="missing required columns"):
        load_lifecycle_rules(tmp_path)
