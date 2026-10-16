"""Classify period movements while keeping effective time separate from knowledge time."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from aisc_imis.board_adjusted_membership import (
    BoardAdjustedMembershipView,
    build_board_adjusted_membership,
)
from aisc_imis.board_pending_actions import (
    ActionKind,
    ActionStatus,
    BoardPendingActions,
)
from aisc_imis.lifecycle_period_movements import (
    DimensionTransfer,
    EvidenceCorrection,
    MovementFinding,
    PeriodMembershipMovementAnalysis,
    analyze_period_membership_movements,
)
from aisc_imis.lifecycle_rules import LifecycleRules
from aisc_imis.member_ledger import MemberLedgerEntry
from aisc_imis.operational_membership_summary import summarize_operational_membership
from aisc_imis.period_membership_balance import (
    PeriodMembershipBalance,
    reconcile_membership_balance,
)


@dataclass(frozen=True)
class QuarterlyMovementRow:
    """One counted state change, backed by iMIS evidence or a Board decision."""

    subject_key: str
    measure: str
    action: str
    effective_date: date
    proposed_date: date | None
    approved_date: date | None
    recorded_date: date | None
    reason: str
    evidence: tuple[MemberLedgerEntry, ...] = ()
    action_id: str | None = None
    source_document_ref: str | None = None
    category: str | None = None


@dataclass(frozen=True)
class NoncountedBoardAction:
    action_id: str
    subject_key: str
    status: ActionStatus
    proposed_date: date | None
    approved_date: date | None
    effective_date: date | None
    recorded_date: date | None
    reason: str
    source_document_ref: str


@dataclass(frozen=True)
class QuarterlyMovementResult:
    start_date: date
    end_date: date
    report_cutoff: date
    counted: tuple[QuarterlyMovementRow, ...]
    noncounted: tuple[NoncountedBoardAction, ...]
    operational_total_change: int | None
    board_adjusted_total_change: int | None
    operational_balance: PeriodMembershipBalance
    opening_board_view: BoardAdjustedMembershipView
    closing_board_view: BoardAdjustedMembershipView
    membership_grouping_transfers: tuple[DimensionTransfer, ...]
    category_transfers: tuple[DimensionTransfer, ...]
    applied_corrections: tuple[EvidenceCorrection, ...]
    findings: tuple[MovementFinding, ...]
    movement: PeriodMembershipMovementAnalysis


def _day(value: date | datetime | None) -> date | None:
    return value.date() if isinstance(value, datetime) else value


def classify_quarterly_movements(
    entries: Iterable[MemberLedgerEntry],
    start_date: date,
    end_date: date,
    report_cutoff: date,
    rules: LifecycleRules,
    board_actions: BoardPendingActions,
    categories: Iterable[str],
    corrections: Iterable[EvidenceCorrection] = (),
    join_measures: Mapping[str, str] | None = None,
) -> QuarterlyMovementResult:
    """Classify ``[start_date, end_date)`` using records known by ``report_cutoff``.

    ``join_measures`` optionally maps a Member Type to M2 or M3. Unmapped joins
    use M2. Reinstatements and resignations use M4; expulsions use M5.
    """
    if end_date <= start_date or report_cutoff < end_date - timedelta(days=1):
        raise ValueError("The report cutoff must cover a nonempty period's last day.")
    if start_date <= date.min + timedelta(days=1):
        raise ValueError(
            "The start date needs two preceding dates for the opening view."
        )
    measures = dict(join_measures or {})
    if any(value not in {"M2", "M3"} for value in measures.values()):
        raise ValueError("Join measures must be M2 or M3.")
    ledger = tuple(entries)
    selected_categories = tuple(categories)
    selected_corrections = tuple(corrections)
    movement = analyze_period_membership_movements(
        ledger, start_date, end_date, rules, selected_corrections, report_cutoff
    )
    balance = reconcile_membership_balance(
        ledger,
        start_date,
        end_date,
        selected_categories,
        rules,
        selected_corrections,
        knowledge_cutoff=report_cutoff,
    )
    opening_date = start_date - timedelta(days=1)
    closing_date = end_date - timedelta(days=1)
    opening = summarize_operational_membership(
        ledger,
        opening_date,
        opening_date - timedelta(days=1),
        selected_categories,
        rules,
        selected_corrections,
        report_cutoff,
    )
    closing = summarize_operational_membership(
        ledger,
        closing_date,
        opening_date,
        selected_categories,
        rules,
        selected_corrections,
        report_cutoff,
    )
    opening_board = build_board_adjusted_membership(
        opening, board_actions, report_cutoff
    )
    closing_board = build_board_adjusted_membership(
        closing, board_actions, report_cutoff
    )
    counted: list[QuarterlyMovementRow] = []
    for member in movement.contributors:
        for action in member.dated_actions:
            if action.action not in {"joined", "reinstated", "resigned", "expelled"}:
                continue
            measure = (
                measures.get(member.closing_member_type or "", "M2")
                if action.action == "joined"
                else "M5"
                if action.action == "expelled"
                else "M4"
            )
            recorded = max(
                (
                    _day(item.record.recorded_date) or _day(item.record.observed_date)
                    for item in action.supporting_evidence
                ),
                default=None,
            )
            counted.append(
                QuarterlyMovementRow(
                    member.subject_key,
                    measure,
                    action.action,
                    action.effective_date,
                    None,
                    None,
                    recorded,
                    "Confirmed operational state change",
                    action.supporting_evidence,
                    category=action.category,
                )
            )

    closing_decisions = {
        decision.action_id: decision for decision in closing_board.decisions
    }
    opening_decisions = {
        decision.action_id: decision for decision in opening_board.decisions
    }
    operational_keys = {row.subject_key for row in counted}
    noncounted: list[NoncountedBoardAction] = []
    for board_action in board_actions.actions:
        visible = [
            revision
            for revision in board_action.revisions
            if revision.status_date <= report_cutoff
        ]
        if not visible:
            continue
        revision = visible[-1]
        approved = next(
            (
                item
                for item in reversed(visible)
                if item.status is ActionStatus.APPROVED
            ),
            None,
        )
        proposed = next(
            (item for item in visible if item.status is ActionStatus.PROPOSED), None
        )
        recorded = next(
            (item for item in visible if item.status is ActionStatus.RECORDED_IN_IMIS),
            None,
        )
        effective = (
            (approved.effective_date or approved.status_date)
            if approved
            else revision.effective_date
        )
        if effective is None:
            effective = revision.status_date
        if (
            not start_date <= effective < end_date
            and not start_date <= revision.status_date < end_date
        ):
            continue
        decision = closing_decisions.get(board_action.action_id)
        opening_decision = opening_decisions.get(board_action.action_id)
        key = revision.imis_id or revision.member_ref
        applied = decision is not None and decision.disposition == "applied"
        already_open = (
            opening_decision is not None and opening_decision.disposition == "applied"
        )
        eligible_kind = revision.action_kind in {
            ActionKind.NEW_MEMBER_APPROVAL,
            ActionKind.EXPULSION,
        }
        if (
            applied
            and not already_open
            and eligible_kind
            and key not in operational_keys
            and start_date <= effective < end_date
        ):
            counted.append(
                QuarterlyMovementRow(
                    key,
                    measures.get(revision.desired_member_type or "", "M2")
                    if revision.action_kind is ActionKind.NEW_MEMBER_APPROVAL
                    else "M5",
                    "joined"
                    if revision.action_kind is ActionKind.NEW_MEMBER_APPROVAL
                    else "expelled",
                    effective,
                    proposed.status_date if proposed else None,
                    approved.status_date if approved else None,
                    recorded.status_date if recorded else None,
                    approved.rationale if approved else revision.rationale,
                    action_id=board_action.action_id,
                    source_document_ref=revision.source_document_ref,
                    category=revision.desired_category,
                )
            )
            continue
        reason = (
            "Operational state change already counted"
            if key in operational_keys and eligible_kind
            else "Board correction is tracked separately from joins and exits"
            if revision.action_kind is ActionKind.CORRECTION and applied
            else "Action was already effective before this period"
            if already_open
            else decision.disposition
            if decision
            else "No visible Board decision"
        )
        noncounted.append(
            NoncountedBoardAction(
                board_action.action_id,
                key,
                revision.status,
                proposed.status_date if proposed else None,
                approved.status_date if approved else None,
                effective,
                recorded.status_date if recorded else None,
                reason,
                revision.source_document_ref,
            )
        )

    operational_change = (
        None
        if not balance.overall.complete or balance.overall.difference != 0
        else balance.overall.closing - balance.overall.opening
    )
    board_change = (
        None
        if opening_board.adjusted.overall.total is None
        or closing_board.adjusted.overall.total is None
        else closing_board.adjusted.overall.total - opening_board.adjusted.overall.total
    )
    findings = list(balance.findings)
    if operational_change is not None and board_change is not None:
        expected_board_change = (
            operational_change
            + closing_board.adjustments.overall
            - opening_board.adjustments.overall
        )
        if expected_board_change != board_change:
            findings.append(
                MovementFinding(
                    "board_movement_difference",
                    "Operational movement and Board adjustment changes do not reconcile to Board views.",
                )
            )
    return QuarterlyMovementResult(
        start_date,
        end_date,
        report_cutoff,
        tuple(counted),
        tuple(noncounted),
        operational_change,
        board_change,
        balance,
        opening_board,
        closing_board,
        movement.membership_grouping_transfers,
        movement.category_transfers,
        movement.applied_corrections,
        tuple(findings),
        movement,
    )
