"""Read-only Board overlay on a dated operational membership summary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from aisc_imis.board_pending_actions import (
    ActionKind,
    ActionRevision,
    ActionStatus,
    BoardPendingActions,
)
from aisc_imis.lifecycle_rules import Countability
from aisc_imis.operational_membership_summary import (
    OperationalMembershipSummary,
    SummaryMemberEvidence,
)


@dataclass(frozen=True)
class BoardMemberState:
    subject_key: str
    category: str | None
    member_type: str | None
    action_id: str | None = None
    reason: str | None = None
    source_document_ref: str | None = None


@dataclass(frozen=True)
class BoardCount:
    confirmed_count: int
    total: int | None
    contributors: tuple[BoardMemberState, ...]


@dataclass(frozen=True)
class BoardCounts:
    overall: BoardCount
    categories: dict[str, BoardCount]
    member_types: dict[str, BoardCount]


@dataclass(frozen=True)
class BoardAdjustments:
    overall: int
    categories: dict[str, int]
    member_types: dict[str, int]


@dataclass(frozen=True)
class BoardMemberDecision:
    action_id: str
    revision_id: str
    subject_key: str
    status: ActionStatus
    disposition: str
    reason: str
    source_document_ref: str
    operational_countable: bool | None
    adjusted_countable: bool | None


@dataclass(frozen=True)
class BoardFinding:
    code: str
    message: str
    action_ids: tuple[str, ...]


@dataclass(frozen=True)
class BoardAdjustedMembershipView:
    operational: OperationalMembershipSummary
    adjustments: BoardAdjustments
    adjusted: BoardCounts
    decisions: tuple[BoardMemberDecision, ...]
    findings: tuple[BoardFinding, ...]
    board_cutoff: date


def build_board_adjusted_membership(
    operational: OperationalMembershipSummary,
    pending: BoardPendingActions,
    knowledge_cutoff: date | None = None,
) -> BoardAdjustedMembershipView:
    """Apply eligible Board actions without modifying the operational summary.

    Only revisions visible by the summary's as-of date are considered. An
    approved revision needs both its status date and effective date (if given)
    within the cutoff. Unknown states and competing actions are skipped.
    """
    cutoff = knowledge_cutoff or operational.as_of_date
    if cutoff < operational.as_of_date:
        raise ValueError("knowledge_cutoff must be on or after the view date.")
    confirmed = {item.subject_key: item for item in operational.overall.contributors}
    movements = {item.subject_key: item for item in operational.movement.contributors}
    states = {
        key: BoardMemberState(key, item.category, item.member_type)
        for key, item in confirmed.items()
    }
    unknown = set(operational.unknown_member_ids)
    operational_countable: dict[str, bool] = {
        key: False
        for key, item in movements.items()
        if item.closing_countability is Countability.NOT_COUNTABLE
        and key not in unknown
    }
    operational_countable.update({key: True for key in confirmed if key not in unknown})
    selected = []
    for action in pending.actions:
        revisions = [
            revision for revision in action.revisions if revision.status_date <= cutoff
        ]
        revision = revisions[-1] if revisions else action.revisions[0]
        approval = revision
        if revision.status is ActionStatus.RECORDED_IN_IMIS:
            approval = next(
                (
                    candidate
                    for candidate in reversed(revisions[:-1])
                    if candidate.status is ActionStatus.APPROVED
                ),
                revision,
            )
        selected.append((action.action_id, revision, approval, bool(revisions)))

    duplicate_ids = {
        action_id
        for group in pending.possible_duplicates
        for action_id in group.action_ids
    }
    active_by_subject: dict[str, list[str]] = {}
    for action_id, revision, approval, visible in selected:
        if (
            visible
            and revision.status
            in {ActionStatus.APPROVED, ActionStatus.RECORDED_IN_IMIS}
            and approval.status is ActionStatus.APPROVED
            and approval.status_date <= cutoff
            and (approval.effective_date or approval.status_date) <= operational.as_of_date
            and not (
                revision.status is ActionStatus.RECORDED_IN_IMIS
                and _operational_confirms(
                    approval,
                    operational_countable.get(revision.imis_id or revision.member_ref),
                    confirmed.get(revision.imis_id or revision.member_ref),
                )
            )
        ):
            active_by_subject.setdefault(
                revision.imis_id or revision.member_ref, []
            ).append(action_id)
    conflicting_ids = {
        action_id
        for group in active_by_subject.values()
        if len(group) > 1
        for action_id in group
    }

    decisions: list[BoardMemberDecision] = []
    findings: list[BoardFinding] = []
    for action_id, revision, approval, visible in selected:
        key = revision.imis_id or revision.member_ref
        movement = movements.get(key)
        before = operational_countable.get(key)
        after = before
        disposition = "applied"
        if (
            not visible
            or approval.status_date > cutoff
            or (approval.effective_date or approval.status_date) > operational.as_of_date
        ):
            disposition = "after-cutoff"
        elif (
            revision.status
            not in {ActionStatus.APPROVED, ActionStatus.RECORDED_IN_IMIS}
            or approval.status is not ActionStatus.APPROVED
        ):
            disposition = "not-approved"
        elif revision.status is ActionStatus.RECORDED_IN_IMIS and _operational_confirms(
            approval, before, confirmed.get(key)
        ):
            disposition = "recorded"
        elif action_id in duplicate_ids:
            disposition = "possible-duplicate"
        elif action_id in conflicting_ids:
            disposition = "conflict"
        elif key in unknown:
            disposition = "unknown-state"
        elif revision.action_kind is ActionKind.NEW_MEMBER_APPROVAL:
            if before is True:
                disposition = "already-counted"
            else:
                states[key] = BoardMemberState(
                    key,
                    movement.closing_category if movement else None,
                    approval.member_type
                    or (movement.closing_member_type if movement else None),
                    action_id,
                    approval.rationale,
                    approval.source_document_ref,
                )
                after = True
        elif before is None:
            disposition = "unknown-state"
        elif revision.action_kind is ActionKind.EXPULSION:
            if before is False:
                disposition = "already-absent"
            else:
                del states[key]
                after = False
        else:
            if before is False and approval.desired_countable is not True:
                disposition = "already-absent"
            else:
                old = states.get(key)
                after = (
                    before
                    if approval.desired_countable is None
                    else approval.desired_countable
                )
                if after:
                    states[key] = BoardMemberState(
                        key,
                        approval.desired_category
                        or (
                            old.category
                            if old
                            else movement.closing_category
                            if movement
                            else None
                        ),
                        approval.desired_member_type
                        or (
                            old.member_type
                            if old
                            else movement.closing_member_type
                            if movement
                            else None
                        ),
                        action_id,
                        approval.rationale,
                        approval.source_document_ref,
                    )
                else:
                    states.pop(key, None)
        decisions.append(
            BoardMemberDecision(
                action_id,
                revision.revision_id,
                key,
                revision.status,
                disposition,
                approval.rationale,
                approval.source_document_ref,
                before,
                after,
            )
        )
        if disposition not in {"applied", "recorded", "not-approved"}:
            code = disposition.replace("-", "_")
            findings.append(
                BoardFinding(
                    code, f"Board action {action_id}: {disposition}.", (action_id,)
                )
            )
        if (
            revision.status is ActionStatus.RECORDED_IN_IMIS
            and disposition == "applied"
        ):
            findings.append(
                BoardFinding(
                    "recording_unconfirmed",
                    f"Board action {action_id} is marked recorded, but operational state does not confirm it.",
                    (action_id,),
                )
            )

    items = tuple(states.values())

    def count(
        selected_items: tuple[BoardMemberState, ...], complete: bool
    ) -> BoardCount:
        return BoardCount(
            len(selected_items),
            len(selected_items) if complete else None,
            selected_items,
        )

    missing_category = tuple(
        item.subject_key for item in items if item.category is None
    )
    missing_type = tuple(item.subject_key for item in items if item.member_type is None)
    unselected_category = tuple(
        item.subject_key
        for item in items
        if item.category is not None and item.category not in operational.categories
    )
    for key in missing_category:
        if key not in operational.missing_category_member_ids:
            findings.append(
                BoardFinding(
                    "missing_category",
                    f"Board-adjusted member {key} has no Category.",
                    tuple(
                        d.action_id
                        for d in decisions
                        if d.subject_key == key and d.disposition == "applied"
                    ),
                )
            )
    for key in missing_type:
        if key not in operational.missing_member_type_member_ids:
            findings.append(
                BoardFinding(
                    "missing_member_type",
                    f"Board-adjusted member {key} has no Member Type.",
                    tuple(
                        d.action_id
                        for d in decisions
                        if d.subject_key == key and d.disposition == "applied"
                    ),
                )
            )
    for key in unselected_category:
        if states[key].action_id is not None:
            findings.append(
                BoardFinding(
                    "unselected_category",
                    f"Board-adjusted member {key} has a Category outside the selected codes.",
                    (states[key].action_id,),
                )
            )
    categories = {
        code: count(
            tuple(item for item in items if item.category == code),
            operational.categories[code].total is not None
            and not missing_category
            and not unselected_category,
        )
        for code in operational.categories
    }
    types = {
        code: count(
            tuple(item for item in items if item.member_type == code),
            operational.overall.total is not None and not missing_type,
        )
        for code in sorted(
            set(operational.member_types)
            | {item.member_type for item in items if item.member_type is not None}
        )
    }
    adjusted = BoardCounts(
        count(items, operational.overall.total is not None), categories, types
    )
    adjustments = BoardAdjustments(
        adjusted.overall.confirmed_count - operational.overall.confirmed_count,
        {
            code: value.confirmed_count - operational.categories[code].confirmed_count
            for code, value in categories.items()
        },
        {
            code: value.confirmed_count - operational.member_types[code].confirmed_count
            if code in operational.member_types
            else value.confirmed_count
            for code, value in types.items()
        },
    )
    return BoardAdjustedMembershipView(
        operational, adjustments, adjusted, tuple(decisions), tuple(findings), cutoff
    )


def _operational_confirms(
    revision: ActionRevision,
    countable: bool | None,
    member: SummaryMemberEvidence | None,
) -> bool:
    if revision.action_kind is ActionKind.NEW_MEMBER_APPROVAL:
        return countable is True
    if revision.action_kind is ActionKind.EXPULSION:
        return countable is False
    if countable is None:
        return False
    if revision.desired_countable is False:
        return countable is False
    if member is None:
        return False
    return (
        (revision.desired_countable is None or revision.desired_countable == countable)
        and (
            revision.desired_category is None
            or revision.desired_category == member.category
        )
        and (
            revision.desired_member_type is None
            or revision.desired_member_type == member.member_type
        )
    )
