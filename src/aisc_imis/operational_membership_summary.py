"""Pure, dated operational counts built from reviewed member evidence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from aisc_imis.dated_membership import select_first_join
from aisc_imis.evidence_ledger import CandidateLifecycleEvent, SnapshotStateObservation
from aisc_imis.lifecycle_period_movements import (
    EvidenceCorrection,
    MovementFinding,
    PeriodMembershipMovementAnalysis,
    analyze_period_membership_movements,
)
from aisc_imis.lifecycle_rules import Countability, LifecycleRules
from aisc_imis.member_ledger import MemberLedgerEntry
from aisc_imis.period_membership_balance import (
    PeriodMembershipBalance,
    has_unresolved_period_evidence,
    reconcile_membership_balance,
)


@dataclass(frozen=True)
class SummaryMemberEvidence:
    """One confirmed contributor and the retained records behind its state."""

    subject_key: str
    category: str | None
    member_type: str | None
    supporting_evidence: tuple[MemberLedgerEntry, ...]
    applied_corrections: tuple[EvidenceCorrection, ...] = ()


@dataclass(frozen=True)
class SummaryCount:
    """A lower bound, optional definitive total, and its member-level proof."""

    confirmed_count: int
    total: int | None
    contributors: tuple[SummaryMemberEvidence, ...]


@dataclass(frozen=True)
class OperationalMembershipSummary:
    as_of_date: date
    prior_as_of_date: date
    overall: SummaryCount
    categories: dict[str, SummaryCount]
    member_types: dict[str, SummaryCount]
    unknown_member_ids: tuple[str, ...]
    missing_category_member_ids: tuple[str, ...]
    missing_member_type_member_ids: tuple[str, ...]
    findings: tuple[MovementFinding, ...]
    balance: PeriodMembershipBalance
    movement: PeriodMembershipMovementAnalysis


def select_reporting_month_ends(
    start_date: date, end_date: date, *, quarter_ends_only: bool = False
) -> tuple[date, ...]:
    """Select month ends within an inclusive range, optionally just quarter ends."""
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date.")
    selected: list[date] = []
    year, month = start_date.year, start_date.month
    while (year, month) <= (end_date.year, end_date.month):
        if (year, month) == (date.max.year, 12):
            month_end = date.max
        else:
            next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
            month_end = date(next_year, next_month, 1) - timedelta(days=1)
        if start_date <= month_end <= end_date and (
            not quarter_ends_only or month in {3, 6, 9, 12}
        ):
            selected.append(month_end)
        if month_end == date.max:
            break
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        year, month = next_year, next_month
    return tuple(selected)


def summarize_operational_membership(
    entries: Iterable[MemberLedgerEntry],
    as_of_date: date,
    prior_as_of_date: date,
    category_codes: Iterable[str],
    rules: LifecycleRules,
    corrections: Iterable[EvidenceCorrection] = (),
    knowledge_cutoff: date | None = None,
) -> OperationalMembershipSummary:
    """Count membership through ``as_of_date`` using an explicit prior cutoff.

    Reconciliation covers the day after ``prior_as_of_date`` through
    ``as_of_date``, inclusive. No Board adjustments enter this calculation.
    """
    if prior_as_of_date >= as_of_date:
        raise ValueError("prior_as_of_date must be before as_of_date.")
    if as_of_date == date.max:
        raise ValueError("as_of_date must be before date.max.")
    if knowledge_cutoff is not None and knowledge_cutoff < as_of_date:
        raise ValueError("knowledge_cutoff must be on or after as_of_date.")
    start = prior_as_of_date + timedelta(days=1)
    end = as_of_date + timedelta(days=1)
    supplied_entries = tuple(entries)
    relevant_subjects = {
        entry.record.subject_key
        for entry in supplied_entries
        if _is_relevant_boundary_evidence(entry, end, knowledge_cutoff)
    }
    by_subject: dict[str, list[MemberLedgerEntry]] = defaultdict(list)
    for entry in supplied_entries:
        by_subject[entry.record.subject_key].append(entry)
    for subject_key, subject_entries in by_subject.items():
        selected_join = select_first_join(subject_entries, rules, knowledge_cutoff or as_of_date)
        if selected_join.effective_date is not None and selected_join.effective_date < end:
            relevant_subjects.add(subject_key)
    selected_entries = tuple(
        entry
        for entry in supplied_entries
        if entry.record.subject_key in relevant_subjects
    )
    selected_categories = tuple(category_codes)
    selected_corrections = tuple(corrections)
    balance = reconcile_membership_balance(
        selected_entries, start, end, selected_categories, rules, selected_corrections,
        knowledge_cutoff=knowledge_cutoff,
    )
    movement = analyze_period_membership_movements(
        selected_entries, start, end, rules, selected_corrections, knowledge_cutoff
    )
    unknown: list[str] = []
    missing_category: list[str] = []
    missing_type: list[str] = []
    confirmed: list[SummaryMemberEvidence] = []
    findings = list(balance.findings)
    for member in movement.contributors:
        unresolved = has_unresolved_period_evidence(member, start)
        if (
            member.opening_countability is Countability.UNKNOWN
            or member.closing_countability is Countability.UNKNOWN
            or unresolved
        ):
            unknown.append(member.subject_key)
        if member.closing_countability is Countability.UNKNOWN or unresolved:
            continue
        if member.closing_countability is not Countability.COUNTABLE:
            continue
        corrections_for_member = tuple(
            correction
            for correction in balance.applied_corrections
            if correction.subject_key == member.subject_key
        )
        item = SummaryMemberEvidence(
            member.subject_key,
            member.closing_category,
            member.closing_member_type,
            member.closing_evidence,
            corrections_for_member,
        )
        confirmed.append(item)
        if item.category is None:
            missing_category.append(item.subject_key)
        elif item.category not in selected_categories:
            findings.append(
                MovementFinding(
                    "unselected_category",
                    f"Countable member {item.subject_key} has Category {item.category}, which was not requested.",
                    item.supporting_evidence,
                )
            )
        if item.member_type is None:
            missing_type.append(item.subject_key)
            findings.append(
                MovementFinding(
                    "unknown_member_type",
                    f"Countable member {item.subject_key} has no known Member Type.",
                    item.supporting_evidence,
                )
            )

    def count(items: tuple[SummaryMemberEvidence, ...], complete: bool) -> SummaryCount:
        return SummaryCount(len(items), len(items) if complete else None, items)

    overall = count(tuple(confirmed), balance.overall.complete and not unknown)
    categories = {
        category: count(
            tuple(item for item in confirmed if item.category == category),
            balance.categories[category].complete
            and not unknown
            and not missing_category,
        )
        for category in selected_categories
    }
    member_type_codes = sorted(
        {item.member_type for item in confirmed if item.member_type is not None}
        | {
            member.opening_member_type
            for member in movement.contributors
            if member.opening_member_type is not None
        }
    )
    member_types = {
        member_type: count(
            tuple(item for item in confirmed if item.member_type == member_type),
            overall.total is not None and not missing_type,
        )
        for member_type in member_type_codes
    }
    return OperationalMembershipSummary(
        as_of_date,
        prior_as_of_date,
        overall,
        categories,
        member_types,
        tuple(unknown),
        tuple(missing_category),
        tuple(missing_type),
        tuple(findings),
        balance,
        movement,
    )


def _is_relevant_boundary_evidence(entry: MemberLedgerEntry, end: date, knowledge_cutoff: date | None = None) -> bool:
    """A member enters the population once dated lifecycle evidence can apply."""
    record = entry.record
    if not isinstance(record, (CandidateLifecycleEvent, SnapshotStateObservation)):
        return False
    effective = record.effective_date
    if isinstance(record, SnapshotStateObservation) and effective is None:
        effective = record.observed_date
    when = effective.date() if isinstance(effective, datetime) else effective
    if when is None or when >= end:
        return False
    if knowledge_cutoff is not None:
        known_on = record.recorded_date or record.observed_date
        known_day = known_on.date() if isinstance(known_on, datetime) else known_on
        return known_day is not None and known_day <= knowledge_cutoff
    return any(
        (value.date() if isinstance(value, datetime) else value) < end
        for value in (record.recorded_date, record.observed_date)
        if value is not None
    )
