"""Validate private, append-only records of pending Board actions.

These records are separate from operational iMIS evidence. Loading them does
not apply an action to a member or resolve possible duplicates.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path


class ActionKind(StrEnum):
    NEW_MEMBER_APPROVAL = "new-member-approval"
    EXPULSION = "expulsion"
    CORRECTION = "correction"


class ActionStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    RECORDED_IN_IMIS = "recorded-in-iMIS"


@dataclass(frozen=True)
class ActionRevision:
    action_id: str
    revision_id: str
    prior_revision_id: str | None
    member_ref: str
    action_kind: ActionKind
    status: ActionStatus
    status_date: date
    recorded_by: str
    rationale: str
    source_document_ref: str
    imis_id: str | None = None
    effective_date: date | None = None
    imis_record_ref: str | None = None
    desired_countable: bool | None = None
    desired_category: str | None = None
    desired_member_type: str | None = None
    member_type: str | None = None


@dataclass(frozen=True)
class BoardAction:
    action_id: str
    member_ref: str
    kind: ActionKind
    revisions: tuple[ActionRevision, ...]

    @property
    def current_revision(self) -> ActionRevision:
        """The final revision in this validated append-only chain."""
        return self.revisions[-1]


@dataclass(frozen=True)
class PossibleDuplicateAction:
    member_ref: str
    action_kind: ActionKind
    action_ids: tuple[str, ...]


@dataclass(frozen=True)
class BoardPendingActions:
    actions: tuple[BoardAction, ...]
    possible_duplicates: tuple[PossibleDuplicateAction, ...]


_REQUIRED = frozenset(
    {
        "action_id",
        "revision_id",
        "member_ref",
        "action_kind",
        "status",
        "status_date",
        "recorded_by",
        "rationale",
        "source_document_ref",
    }
)
_OPTIONAL = frozenset(
    {
        "prior_revision_id",
        "imis_id",
        "effective_date",
        "imis_record_ref",
        "desired_countable",
        "desired_category",
        "desired_member_type",
        "member_type",
    }
)
_CORRECTION = frozenset(
    {"desired_countable", "desired_category", "desired_member_type"}
)
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


def load_board_pending_actions(path: str | Path) -> BoardPendingActions:
    """Load a version 1 JSON file and report distinct possible duplicate actions.

    Revisions are listed in append order. Each action has one root revision,
    and each later revision points to its immediate predecessor.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid Board action JSON: {error}") from error
    if not isinstance(data, dict):
        raise ValueError("Board action file must be an object.")
    if set(data) != {"version", "revisions"}:
        raise ValueError(
            "Board action file requires only version and revisions; "
            f"found {sorted(data)}."
        )
    if type(data["version"]) is not int or data["version"] != 1:
        raise ValueError("Board action version must be 1.")
    if not isinstance(data["revisions"], list):
        raise ValueError("Board action revisions must be a list.")

    revisions_by_action: dict[str, list[ActionRevision]] = {}
    seen_revisions: set[str] = set()
    for index, raw in enumerate(data["revisions"]):
        revision = _parse_revision(raw, index)
        label = f"revisions[{index}]"
        if revision.revision_id in seen_revisions:
            raise ValueError(f"{label}.revision_id must be unique.")
        seen_revisions.add(revision.revision_id)
        chain = revisions_by_action.setdefault(revision.action_id, [])
        if not chain:
            if revision.prior_revision_id is not None:
                raise ValueError(
                    f"{label}.prior_revision_id must be absent for the first revision "
                    "of an action."
                )
        else:
            previous = chain[-1]
            if revision.prior_revision_id != previous.revision_id:
                raise ValueError(
                    f"{label}.prior_revision_id must equal the previous revision_id "
                    f"{previous.revision_id!r} for this action."
                )
            if revision.member_ref != previous.member_ref:
                raise ValueError(f"{label}.member_ref must remain the same in a chain.")
            if revision.action_kind != previous.action_kind:
                raise ValueError(
                    f"{label}.action_kind must remain the same in a chain."
                )
            if revision.status_date < previous.status_date:
                raise ValueError(
                    f"{label}.status_date must not precede the prior revision."
                )
        chain.append(revision)

    actions = tuple(
        BoardAction(action_id, chain[0].member_ref, chain[0].action_kind, tuple(chain))
        for action_id, chain in revisions_by_action.items()
    )
    by_member_kind: dict[tuple[str, ActionKind], list[str]] = {}
    for action in actions:
        by_member_kind.setdefault((action.member_ref, action.kind), []).append(
            action.action_id
        )
    duplicates = tuple(
        PossibleDuplicateAction(member_ref, kind, tuple(action_ids))
        for (member_ref, kind), action_ids in by_member_kind.items()
        if len(action_ids) > 1
    )
    return BoardPendingActions(actions, duplicates)


def _parse_revision(raw: object, index: int) -> ActionRevision:
    label = f"revisions[{index}]"
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be an object.")
    missing = _REQUIRED - raw.keys()
    extra = raw.keys() - (_REQUIRED | _OPTIONAL)
    if missing or extra:
        raise ValueError(
            f"{label} has missing fields {sorted(missing)} or extra fields "
            f"{sorted(extra)}."
        )
    kind = _enum(raw, "action_kind", ActionKind, label)
    status = _enum(raw, "status", ActionStatus, label)
    if kind is ActionKind.CORRECTION:
        if not _CORRECTION.intersection(raw):
            raise ValueError(f"{label} correction requires a desired target field.")
    elif _CORRECTION.intersection(raw):
        fields = sorted(_CORRECTION.intersection(raw))
        raise ValueError(f"{label} fields {fields} require action_kind correction.")
    if "member_type" in raw and kind is not ActionKind.NEW_MEMBER_APPROVAL:
        raise ValueError(
            f"{label}.member_type requires action_kind new-member-approval."
        )
    if status is ActionStatus.RECORDED_IN_IMIS and "imis_record_ref" not in raw:
        raise ValueError(f"{label}.imis_record_ref is required for recorded-in-iMIS.")

    countable = raw.get("desired_countable")
    if "desired_countable" in raw and type(countable) is not bool:
        raise ValueError(f"{label}.desired_countable must be a boolean.")
    return ActionRevision(
        action_id=_nonblank(raw, "action_id", label),
        revision_id=_nonblank(raw, "revision_id", label),
        prior_revision_id=_optional_string(raw, "prior_revision_id", label),
        member_ref=_nonblank(raw, "member_ref", label),
        action_kind=kind,
        status=status,
        status_date=_date(raw, "status_date", label),
        recorded_by=_nonblank(raw, "recorded_by", label),
        rationale=_nonblank(raw, "rationale", label),
        source_document_ref=_nonblank(raw, "source_document_ref", label),
        imis_id=_optional_string(raw, "imis_id", label),
        effective_date=(
            _date(raw, "effective_date", label) if "effective_date" in raw else None
        ),
        imis_record_ref=_optional_string(raw, "imis_record_ref", label),
        desired_countable=countable,
        desired_category=_optional_string(raw, "desired_category", label),
        desired_member_type=_optional_string(raw, "desired_member_type", label),
        member_type=_optional_string(raw, "member_type", label),
    )


def _nonblank(raw: dict[str, object], field: str, label: str) -> str:
    value = raw[field]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}.{field} must be a nonblank string.")
    return value


def _optional_string(raw: dict[str, object], field: str, label: str) -> str | None:
    return _nonblank(raw, field, label) if field in raw else None


def _date(raw: dict[str, object], field: str, label: str) -> date:
    value = raw[field]
    if not isinstance(value, str) or _ISO_DATE.fullmatch(value) is None:
        raise ValueError(f"{label}.{field} must be an ISO date (YYYY-MM-DD).")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(
            f"{label}.{field} must be a valid ISO date (YYYY-MM-DD)."
        ) from error


def _enum(raw: dict[str, object], field: str, enum: type[StrEnum], label: str):
    value = raw[field]
    try:
        return enum(value)
    except (ValueError, TypeError) as error:
        allowed = ", ".join(item.value for item in enum)
        raise ValueError(f"{label}.{field} must be one of: {allowed}.") from error
