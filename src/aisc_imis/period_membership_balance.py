"""Reconcile confirmed membership counts without inventing balancing entries."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime

from aisc_imis.evidence_ledger import CandidateLifecycleEvent
from aisc_imis.lifecycle_period_movements import (
    EvidenceCorrection,
    MovementFinding,
    analyze_period_membership_movements,
)
from aisc_imis.lifecycle_rules import Countability, LifecycleRules
from aisc_imis.member_ledger import MemberLedgerEntry
from aisc_imis.normalization_contracts import SourceReference

ACTION_SIGNS = {"joined": 1, "reinstated": 1, "resigned": -1, "expelled": -1, "exited": -1}
TERM_NAMES = ("opening", *ACTION_SIGNS, "transfers_in", "transfers_out", "adjustments", "closing")


@dataclass(frozen=True)
class ReviewedBalanceAdjustment:
    """A separately reviewed, signed change to a balance equation."""

    subject_key: str
    effective_date: date
    category: str
    count_change: int
    reason: str
    source_references: tuple[SourceReference, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_references", tuple(self.source_references))
        if not self.subject_key.strip() or not self.category.strip() or not self.reason.strip() or not self.source_references:
            raise ValueError("Adjustment needs a member, Category, reason, and source references.")
        if not isinstance(self.effective_date, date) or not isinstance(self.count_change, int) or isinstance(self.count_change, bool) or self.count_change == 0:
            raise ValueError("Adjustment needs a date and nonzero integer count change.")


@dataclass(frozen=True)
class BalanceTermEvidence:
    subject_key: str
    effective_date: date
    category: str | None
    count_change: int
    ledger_evidence: tuple[MemberLedgerEntry, ...] = ()
    source_references: tuple[SourceReference, ...] = ()
    reason: str | None = None


@dataclass(frozen=True)
class MembershipBalanceLine:
    """One overall or source Category equation; unknown boundaries remain None."""

    category: str | None
    complete: bool
    opening: int | None
    movements: dict[str, int]
    transfers_in: int
    transfers_out: int
    adjustments: int
    closing: int | None
    expected_closing: int | None
    difference: int | None
    terms: dict[str, tuple[BalanceTermEvidence, ...]]


@dataclass(frozen=True)
class PeriodMembershipBalance:
    start_date: date
    end_date: date
    overall: MembershipBalanceLine
    categories: dict[str, MembershipBalanceLine]
    applied_corrections: tuple[EvidenceCorrection, ...]
    findings: tuple[MovementFinding, ...]


def reconcile_membership_balance(
    entries: Iterable[MemberLedgerEntry],
    start_date: date,
    end_date: date,
    categories: Iterable[str],
    rules: LifecycleRules,
    corrections: Iterable[EvidenceCorrection] = (),
    adjustments: Iterable[ReviewedBalanceAdjustment] = (),
) -> PeriodMembershipBalance:
    """Compare closing count with opening plus confirmed movements and reviews.

    The period is ``[start_date, end_date)``. Category labels are source codes.
    A difference is ``closing - expected_closing``; it is never used as an
    adjustment. Unknown boundaries suppress the affected equation's difference.
    """
    selected = tuple(categories)
    if len(selected) != len(set(selected)) or any(not code.strip() for code in selected):
        raise ValueError("Category codes must be nonblank and unique.")
    movement = analyze_period_membership_movements(entries, start_date, end_date, rules, corrections)
    reviewed = tuple(adjustments)
    findings = list(movement.findings)
    terms: dict[str | None, dict[str, list[BalanceTermEvidence]]] = {
        category: {name: [] for name in TERM_NAMES} for category in (None, *selected)
    }
    overall_complete = True
    category_complete = {category: True for category in selected}

    def add(name: str, item: BalanceTermEvidence) -> None:
        terms[None][name].append(item)
        if item.category in category_complete:
            terms[item.category][name].append(item)

    for member in movement.contributors:
        unknown_count = Countability.UNKNOWN in {member.opening_countability, member.closing_countability}
        unresolved_state = any(
            finding.code in {"unresolved_lifecycle_evidence", "invalid_snapshot_field", "same_day_state_contradiction"}
            and any(
                (not isinstance(entry.record, CandidateLifecycleEvent) or entry.record.event_name != "transferred")
                and (
                    member.opening_countability is Countability.UNKNOWN
                    or _evidence_day(entry) is None
                    or _evidence_day(entry) >= start_date
                )
                for entry in finding.supporting_evidence
            )
            for finding in member.findings
        )
        if unknown_count or unresolved_state:
            overall_complete = False
            category_complete = dict.fromkeys(selected, False)
        for name, state, category, evidence, when in (
            ("opening", member.opening_countability, member.opening_category, member.opening_evidence, start_date),
            ("closing", member.closing_countability, member.closing_category, member.closing_evidence, end_date),
        ):
            if state is Countability.COUNTABLE:
                add(name, BalanceTermEvidence(member.subject_key, when, category, 1, evidence))
                if category is None:
                    category_complete = dict.fromkeys(selected, False)
                    findings.append(MovementFinding("unknown_category", f"Countable member {member.subject_key} has no known Category at a period boundary.", evidence))
        for action in member.dated_actions:
            if action.action not in ACTION_SIGNS:
                continue
            add(action.action, BalanceTermEvidence(member.subject_key, action.effective_date, action.category, ACTION_SIGNS[action.action], action.supporting_evidence))
            if action.category is None:
                category_complete = dict.fromkeys(selected, False)
                findings.append(MovementFinding("unknown_category", f"Movement for {member.subject_key} has no known Category.", action.supporting_evidence))
        for transfer in member.category_transfers:
            add("transfers_out", BalanceTermEvidence(member.subject_key, transfer.effective_date, transfer.outgoing, -1, transfer.supporting_evidence))
            add("transfers_in", BalanceTermEvidence(member.subject_key, transfer.effective_date, transfer.incoming, 1, transfer.supporting_evidence))
        if not unknown_count:
            actual_change = int(member.closing_countability is Countability.COUNTABLE) - int(member.opening_countability is Countability.COUNTABLE)
            classified_change = sum(ACTION_SIGNS[action.action] for action in member.dated_actions if action.action in ACTION_SIGNS)
            if actual_change != classified_change:
                findings.append(MovementFinding("unclassified_movement", f"Confirmed boundary change for {member.subject_key} is not explained by classified lifecycle actions.", member.supporting_evidence))

    for adjustment in reviewed:
        if not start_date <= adjustment.effective_date < end_date:
            raise ValueError("Adjustment effective date must fall within the period.")
        add("adjustments", BalanceTermEvidence(adjustment.subject_key, adjustment.effective_date, adjustment.category, adjustment.count_change, source_references=adjustment.source_references, reason=adjustment.reason))
        if adjustment.category not in selected:
            findings.append(MovementFinding("unselected_adjustment_category", f"Adjustment Category {adjustment.category} was not requested."))

    def make_line(category: str | None, complete: bool) -> MembershipBalanceLine:
        line_terms = {name: tuple(items) for name, items in terms[category].items()}
        opening = len(line_terms["opening"]) if complete else None
        closing = len(line_terms["closing"]) if complete else None
        actions = {name: len(line_terms[name]) for name in ACTION_SIGNS}
        transfers_in = len(line_terms["transfers_in"]) if category is not None else 0
        transfers_out = len(line_terms["transfers_out"]) if category is not None else 0
        adjustment_total = sum(item.count_change for item in line_terms["adjustments"])
        expected = None if opening is None else opening + sum(ACTION_SIGNS[name] * count for name, count in actions.items()) + transfers_in - transfers_out + adjustment_total
        difference = None if closing is None or expected is None else closing - expected
        if difference:
            label = "overall" if category is None else f"Category {category}"
            findings.append(MovementFinding("balance_difference", f"{label} closing count differs from expected by {difference}."))
        return MembershipBalanceLine(category, complete, opening, actions, transfers_in, transfers_out, adjustment_total, closing, expected, difference, line_terms)

    overall = make_line(None, overall_complete)
    category_lines = {category: make_line(category, category_complete[category]) for category in selected}
    return PeriodMembershipBalance(start_date, end_date, overall, category_lines, movement.applied_corrections, tuple(findings))


def _evidence_day(entry: MemberLedgerEntry) -> date | None:
    value = entry.record.effective_date or entry.record.observed_date
    return value.date() if isinstance(value, datetime) else value
