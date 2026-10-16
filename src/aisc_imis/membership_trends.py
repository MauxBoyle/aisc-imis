"""Explainable trends over consecutive operational membership cutoffs."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from aisc_imis.evidence_ledger import CandidateLifecycleEvent, SnapshotStateObservation
from aisc_imis.lifecycle_period_movements import (
    DimensionTransfer,
    EvidenceCorrection,
    MemberMovementContributor,
    MovementFinding,
)
from aisc_imis.lifecycle_rules import Countability, LifecycleRules
from aisc_imis.member_ledger import MemberLedgerEntry
from aisc_imis.normalization_contracts import SourceReference
from aisc_imis.operational_membership_summary import (
    OperationalMembershipSummary,
    SummaryCount,
    summarize_operational_membership,
)
from aisc_imis.period_membership_balance import (
    BalanceTermEvidence,
    MembershipBalanceLine,
    has_unresolved_period_evidence,
)


@dataclass(frozen=True)
class MembershipTrendRow:
    """One overall or source Category row for a period."""

    category: str | None
    opening_confirmed_count: int
    opening_count: int | None
    closing_confirmed_count: int
    closing_count: int | None
    movements: dict[str, int]
    transfers_in: int
    transfers_out: int
    adjustments: int
    net_change: int | None
    expected_closing: int | None
    difference: int | None
    terms: dict[str, tuple[BalanceTermEvidence, ...]]


@dataclass(frozen=True)
class MemberTrendDecision:
    """A member's boundaries, classifications, findings, and source proof."""

    subject_key: str
    opening_countability: Countability
    closing_countability: Countability
    opening_status: str
    closing_status: str
    inclusion_reason: str
    opening_category: str | None
    closing_category: str | None
    opening_member_type: str | None
    closing_member_type: str | None
    lifecycle_actions: tuple[str, ...]
    category_transfers: tuple[DimensionTransfer, ...]
    membership_grouping_transfers: tuple[DimensionTransfer, ...]
    findings: tuple[MovementFinding, ...]
    applied_corrections: tuple[EvidenceCorrection, ...]
    terms: dict[str, tuple[BalanceTermEvidence, ...]]
    ledger_evidence: tuple[MemberLedgerEntry, ...]
    source_references: tuple[SourceReference, ...]


@dataclass(frozen=True)
class MembershipTrendPeriod:
    prior_as_of_date: date
    as_of_date: date
    summary: OperationalMembershipSummary
    overall: MembershipTrendRow
    categories: dict[str, MembershipTrendRow]
    decisions: tuple[MemberTrendDecision, ...]
    findings: tuple[MovementFinding, ...]


@dataclass(frozen=True)
class MembershipTrends:
    as_of_dates: tuple[date, ...]
    periods: tuple[MembershipTrendPeriod, ...]


def build_membership_trends(
    entries: Iterable[MemberLedgerEntry],
    as_of_dates: Iterable[date],
    category_codes: Iterable[str],
    rules: LifecycleRules,
    corrections: Iterable[EvidenceCorrection] = (),
) -> MembershipTrends:
    """Compare adjacent inclusive cutoffs, keeping evidence and uncertainty.

    The first date is a baseline. A missing definitive total stays ``None``;
    the confirmed closing count still shows members supported by evidence.
    """
    dates = tuple(as_of_dates)
    if len(dates) < 2 or any(type(day) is not date for day in dates):
        raise ValueError("Supply at least two dates.")
    if any(earlier >= later for earlier, later in zip(dates, dates[1:], strict=False)):
        raise ValueError("As-of dates must be strictly increasing.")
    selected_entries = tuple(entries)
    selected_categories = tuple(category_codes)
    selected_corrections = tuple(corrections)
    periods = tuple(
        _build_period(
            selected_entries, earlier, later, selected_categories, rules, selected_corrections
        )
        for earlier, later in zip(dates, dates[1:], strict=False)
    )
    return MembershipTrends(dates, periods)


def _build_period(
    entries: tuple[MemberLedgerEntry, ...],
    prior: date,
    current: date,
    categories: tuple[str, ...],
    rules: LifecycleRules,
    corrections: tuple[EvidenceCorrection, ...],
) -> MembershipTrendPeriod:
    summary = summarize_operational_membership(
        entries, current, prior, categories, rules, corrections
    )
    balance = summary.balance
    overall = _row(balance.overall, summary.overall)
    category_rows = {
        code: _row(balance.categories[code], summary.categories[code])
        for code in categories
    }
    decisions = tuple(
        _decision(member, summary)
        for member in summary.movement.contributors
    )
    return MembershipTrendPeriod(
        prior, current, summary, overall, category_rows, decisions, summary.findings
    )


def _row(line: MembershipBalanceLine, count: SummaryCount) -> MembershipTrendRow:
    closing = count.total
    opening = line.opening
    return MembershipTrendRow(
        line.category,
        len(line.terms["opening"]),
        opening,
        count.confirmed_count,
        closing,
        line.movements,
        line.transfers_in,
        line.transfers_out,
        line.adjustments,
        closing - opening if closing is not None and opening is not None else None,
        line.expected_closing,
        line.difference,
        line.terms,
    )


def _decision(
    member: MemberMovementContributor, summary: OperationalMembershipSummary
) -> MemberTrendDecision:
    unresolved = has_unresolved_period_evidence(member, summary.balance.start_date)
    opening = _status(member.opening_countability)
    closing = "uncertain" if unresolved else _status(member.closing_countability)
    reason = {
        "included": "Confirmed countable closing state with resolved evidence.",
        "excluded": "Confirmed noncountable closing state.",
        "uncertain": "Closing countability or period evidence is unresolved.",
    }[closing]
    subject = member.subject_key
    terms = {
        name: tuple(item for item in items if item.subject_key == subject)
        for name, items in summary.balance.overall.terms.items()
    }
    applied = tuple(
        correction
        for correction in summary.balance.applied_corrections
        if correction.subject_key == subject
    )
    related_findings = tuple(
        finding for finding in summary.findings
        if finding not in member.findings
        and any(entry.record.subject_key == subject for entry in finding.supporting_evidence)
    )
    findings = (*member.findings, *related_findings)
    evidence = member.supporting_evidence
    sources = dict.fromkeys(
        (
            source
            for entry in evidence
            for source in _entry_sources(entry)
        ),
    )
    for correction in applied:
        sources.update(dict.fromkeys(correction.source_references))
    return MemberTrendDecision(
        subject,
        member.opening_countability,
        member.closing_countability,
        opening,
        closing,
        reason,
        member.opening_category,
        member.closing_category,
        member.opening_member_type,
        member.closing_member_type,
        member.lifecycle_actions,
        member.category_transfers,
        member.membership_grouping_transfers,
        findings,
        applied,
        terms,
        evidence,
        tuple(sources),
    )


def _status(countability: Countability) -> str:
    if countability is Countability.COUNTABLE:
        return "included"
    if countability is Countability.NOT_COUNTABLE:
        return "excluded"
    return "uncertain"


def _entry_sources(entry: MemberLedgerEntry) -> tuple[SourceReference, ...]:
    record = entry.record
    if isinstance(record, CandidateLifecycleEvent):
        return record.source_references
    if isinstance(record, SnapshotStateObservation):
        return (record.source_reference,)
    return (record.source_reference,)
