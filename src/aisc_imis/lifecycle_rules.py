"""Evaluate reviewed membership lifecycle rules without reading source exports.

The evaluator receives already-observed values from a caller.  It deliberately
does not select source rows, reconcile evidence, or write a report.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path

RULES_FILENAME = "lifecycle-rules.csv"
REQUIRED_COLUMNS = {
    "rule_version",
    "effective_reporting_date",
    "rule_kind",
    "member_type",
    "is_company",
    "is_member",
    "category",
    "event_name",
    "operational_state",
    "countability",
    "allowed_transition",
    "event_target_state",
    "precedence",
    "review_provenance",
}


class Countability(StrEnum):
    """Whether a state is approved for membership reporting."""

    COUNTABLE = "countable"
    NOT_COUNTABLE = "not_countable"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LifecycleObservation:
    """Observed values supplied by an adapter or another caller.

    ``status`` is retained only for caller context.  The initial rule version
    intentionally does not use it to determine countability.
    """

    member_type: str | None = None
    is_company: bool | None = None
    is_member: bool | None = None
    category: str | None = None
    event_name: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class LifecycleFinding:
    """A machine-readable reason the evaluator did not guess."""

    code: str
    message: str
    field: str | None = None


@dataclass(frozen=True)
class LifecycleRule:
    """One reviewed row from the version-controlled rule table."""

    rule_version: str
    effective_reporting_date: date
    rule_kind: str
    member_type: str
    is_company: str
    is_member: str
    category: str
    event_name: str
    operational_state: str
    countability: Countability
    allowed_transition: str
    event_target_state: str
    precedence: int
    review_provenance: str


@dataclass(frozen=True)
class LifecycleRules:
    """Validated, immutable lifecycle-rule configuration."""

    rules: tuple[LifecycleRule, ...]


@dataclass(frozen=True)
class CountabilityDecision:
    """A versioned operational decision plus all review findings."""

    rule_version: str | None
    operational_state: str | None
    countability: Countability
    transition_effect: str | None
    event_target_state: str | None
    findings: tuple[LifecycleFinding, ...]


def load_lifecycle_rules(reference_directory: str | Path) -> LifecycleRules:
    """Load and validate ``lifecycle-rules.csv`` from a reference directory."""
    path = Path(reference_directory) / RULES_FILENAME
    with path.open(encoding="utf-8", newline="") as rule_file:
        reader = csv.DictReader(rule_file)
        fieldnames = set(reader.fieldnames or ())
        missing = REQUIRED_COLUMNS - fieldnames
        if missing:
            raise ValueError(f"lifecycle-rules.csv missing required columns: {sorted(missing)}")
        rows = tuple(_parse_rule(row, index) for index, row in enumerate(reader, 2))

    if not rows:
        raise ValueError("lifecycle-rules.csv must contain at least one rule.")
    return LifecycleRules(rows)


def evaluate_countability(
    observation: LifecycleObservation,
    reporting_date: date,
    rules: LifecycleRules,
) -> CountabilityDecision:
    """Return the approved decision for one observation at ``reporting_date``.

    A reporting date before the first configured version, unapproved values,
    and contradictions return ``unknown`` with findings instead of a guess.
    """
    applicable = [rule for rule in rules.rules if rule.effective_reporting_date <= reporting_date]
    if not applicable:
        return _unknown(
            None,
            "no_applicable_rule_version",
            "No lifecycle rule version applies to this reporting date.",
            "reporting_date",
        )

    effective_date = max(rule.effective_reporting_date for rule in applicable)
    version_rules = [rule for rule in applicable if rule.effective_reporting_date == effective_date]
    rule_version = version_rules[0].rule_version

    if observation.event_name is not None:
        return _evaluate_event(observation, version_rules, rule_version)
    return _evaluate_state(observation, version_rules, rule_version)


def _evaluate_state(
    observation: LifecycleObservation,
    rules: list[LifecycleRule],
    rule_version: str,
) -> CountabilityDecision:
    if observation.member_type is None or not observation.member_type.strip():
        return _unknown(rule_version, "missing_member_type", "Member Type is required.", "member_type")
    if observation.is_company is None:
        return _unknown(rule_version, "missing_is_company", "Is Company is required.", "is_company")
    if observation.is_member is None:
        return _unknown(rule_version, "missing_is_member", "Is Member is required.", "is_member")

    member_type = observation.member_type.strip().upper()
    if member_type.endswith("D") and observation.is_company:
        return _unknown(
            rule_version,
            "company_dependent_conflict",
            "A company record cannot use a dependent Member Type.",
            "member_type",
        )

    matches = [
        rule
        for rule in rules
        if rule.rule_kind == "state" and _matches_state(rule, member_type, observation)
    ]
    if not matches:
        return _unknown(
            rule_version,
            "unsupported_state_combination",
            "This Member Type and observed state combination is not approved.",
            "member_type",
        )
    rule = min(matches, key=lambda item: item.precedence)
    return CountabilityDecision(
        rule_version,
        rule.operational_state,
        rule.countability,
        None,
        None,
        (),
    )


def _evaluate_event(
    observation: LifecycleObservation,
    rules: list[LifecycleRule],
    rule_version: str,
) -> CountabilityDecision:
    event_name = observation.event_name.strip().lower()
    matches = [
        rule
        for rule in rules
        if rule.rule_kind == "event" and rule.event_name.lower() == event_name
    ]
    if not matches:
        return _unknown(
            rule_version,
            "unsupported_transition",
            "This lifecycle event is not an approved transition.",
            "event_name",
        )
    rule = min(matches, key=lambda item: item.precedence)
    return CountabilityDecision(
        rule_version,
        rule.operational_state,
        rule.countability,
        rule.allowed_transition,
        rule.event_target_state,
        (),
    )


def _matches_state(
    rule: LifecycleRule, member_type: str, observation: LifecycleObservation
) -> bool:
    return (
        rule.member_type == member_type
        and _matches_boolean(rule.is_company, observation.is_company)
        and _matches_boolean(rule.is_member, observation.is_member)
        and _matches_text(rule.category, observation.category)
    )


def _matches_boolean(expected: str, observed: bool) -> bool:
    return expected == "*" or expected == str(observed).lower()


def _matches_text(expected: str, observed: str | None) -> bool:
    return expected == "*" or (observed is not None and expected == observed.strip())


def _unknown(
    rule_version: str | None, code: str, message: str, field: str
) -> CountabilityDecision:
    return CountabilityDecision(
        rule_version,
        None,
        Countability.UNKNOWN,
        None,
        None,
        (LifecycleFinding(code, message, field),),
    )


def _parse_rule(row: dict[str, str | None], line_number: int) -> LifecycleRule:
    values = {name: (row.get(name) or "").strip() for name in REQUIRED_COLUMNS}
    blank = [name for name, value in values.items() if not value]
    if blank:
        raise ValueError(f"lifecycle-rules.csv line {line_number} has blank values: {blank}")
    if values["rule_kind"] not in {"state", "event"}:
        raise ValueError(f"lifecycle-rules.csv line {line_number} has invalid rule_kind.")
    try:
        countability = Countability(values["countability"])
        effective_date = date.fromisoformat(values["effective_reporting_date"])
        precedence = int(values["precedence"])
    except ValueError as error:
        raise ValueError(f"lifecycle-rules.csv line {line_number} is invalid: {error}") from error
    return LifecycleRule(
        rule_version=values["rule_version"],
        effective_reporting_date=effective_date,
        rule_kind=values["rule_kind"],
        member_type=values["member_type"],
        is_company=values["is_company"],
        is_member=values["is_member"],
        category=values["category"],
        event_name=values["event_name"],
        operational_state=values["operational_state"],
        countability=countability,
        allowed_transition=values["allowed_transition"],
        event_target_state=values["event_target_state"],
        precedence=precedence,
        review_provenance=values["review_provenance"],
    )
