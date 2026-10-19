"""Select quarterly M5 proposals and expulsions, then export separate CSVs."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, fields
from datetime import date
from pathlib import Path

from aisc_imis.board_pending_actions import (
    ActionKind,
    ActionRevision,
    ActionStatus,
    BoardPendingActions,
)
from aisc_imis.lifecycle_period_movements import MovementFinding
from aisc_imis.quarterly_board_movements import (
    QuarterlyMovementResult,
    QuarterlyMovementRow,
)


@dataclass(frozen=True)
class M5ExpulsionRow:
    subject_key: str
    action_id: str | None
    action_status: str
    proposed_date: date | None
    approved_date: date | None
    effective_date: date | None
    recorded_date: date | None
    report_cutoff: date
    operational_history: str
    board_evidence_refs: str
    lifecycle_evidence_refs: str
    date_basis: str = "event_effective_date"


@dataclass(frozen=True)
class M5Expulsions:
    pending_proposals: tuple[M5ExpulsionRow, ...]
    completed_expulsions: tuple[M5ExpulsionRow, ...]
    counts: dict[str, int]
    findings: tuple[MovementFinding, ...]


def _refs(movement: QuarterlyMovementRow) -> str:
    refs: set[str] = set()
    for entry in movement.evidence:
        refs.add(f"ledger:{entry.record_id}")
        sources = getattr(entry.record, "source_references", None)
        if sources is None:
            sources = (entry.record.source_reference,)
        refs.update(
            f"{source.source_name}:{source.row_reference}" for source in sources
        )
    return "; ".join(sorted(refs))


def _board_dates(
    visible: tuple[ActionRevision, ...],
) -> tuple[date | None, date | None, date | None]:
    proposed = next(
        (
            revision.status_date
            for revision in visible
            if revision.status is ActionStatus.PROPOSED
        ),
        None,
    )
    approved = next(
        (
            revision.status_date
            for revision in visible
            if revision.status is ActionStatus.APPROVED
        ),
        None,
    )
    recorded = next(
        (
            revision.status_date
            for revision in visible
            if revision.status is ActionStatus.RECORDED_IN_IMIS
        ),
        None,
    )
    return proposed, approved, recorded


def _board_refs(visible: tuple[ActionRevision, ...]) -> str:
    return "; ".join(sorted({revision.source_document_ref for revision in visible}))


def build_m5_expulsions(
    movements: QuarterlyMovementResult, board_actions: BoardPendingActions
) -> M5Expulsions:
    """Build two M5 lists from classified movements and visible Board revisions.

    The classifier determines completed events. Board proposals alone never
    become completed rows. A report cutoff can include later evidence for a
    quarter whose effective period remains ``[start_date, end_date)``.
    """
    findings = list(movements.findings)
    visible_by_id: dict[str, tuple[ActionRevision, ...]] = {}
    by_imis_id: dict[str, list[str]] = {}
    pending: list[M5ExpulsionRow] = []
    for action in board_actions.actions:
        if action.kind is not ActionKind.EXPULSION:
            continue
        visible = tuple(
            revision
            for revision in action.revisions
            if revision.status_date <= movements.report_cutoff
        )
        if not visible:
            continue
        visible_by_id[action.action_id] = visible
        ids = {revision.imis_id for revision in visible if revision.imis_id}
        if len(ids) > 1:
            findings.append(
                MovementFinding(
                    "m5_conflicting_board_imis_ids",
                    f"Board action {action.action_id} has conflicting visible iMIS IDs.",
                )
            )
        elif ids and visible[-1].status in {
            ActionStatus.APPROVED,
            ActionStatus.RECORDED_IN_IMIS,
        }:
            by_imis_id.setdefault(next(iter(ids)), []).append(action.action_id)
        latest = visible[-1]
        proposed, approved, recorded = _board_dates(visible)
        if (
            latest.status is ActionStatus.PROPOSED
            and proposed is not None
            and movements.start_date <= proposed < movements.end_date
        ):
            pending.append(
                M5ExpulsionRow(
                    next(iter(ids)) if len(ids) == 1 else action.member_ref,
                    action.action_id,
                    latest.status.value,
                    proposed,
                    approved,
                    latest.effective_date,
                    recorded,
                    movements.report_cutoff,
                    "not_recorded",
                    _board_refs(visible),
                    "",
                    "board_effective_date" if latest.effective_date else "board_status_date",
                )
            )
        elif latest.status in {ActionStatus.REJECTED, ActionStatus.WITHDRAWN}:
            findings.append(
                MovementFinding(
                    f"m5_{latest.status.value}_action",
                    f"Board expulsion {action.action_id} is {latest.status.value}; document: {latest.source_document_ref}.",
                )
            )

    completed: list[M5ExpulsionRow] = []
    classified = [
        row
        for row in movements.counted
        if row.measure == "M5" and row.action == "expelled"
    ]
    seen: set[tuple[str, date]] = set()
    for movement in classified:
        identity = (movement.subject_key, movement.effective_date)
        if identity in seen:
            findings.append(
                MovementFinding(
                    "m5_duplicate_classified_expulsion",
                    f"Repeated counted expulsion for {movement.subject_key} on {movement.effective_date}.",
                    movement.evidence,
                )
            )
            continue
        seen.add(identity)
        operational = bool(movement.evidence)
        matches = []
        if operational:
            for candidate_id in by_imis_id.get(movement.subject_key, []):
                revisions = visible_by_id[candidate_id]
                approval = next(
                    (
                        revision
                        for revision in reversed(revisions)
                        if revision.status is ActionStatus.APPROVED
                    ),
                    None,
                )
                if (
                    approval
                    and (approval.effective_date or approval.status_date)
                    == movement.effective_date
                ):
                    matches.append(candidate_id)
        if len(matches) > 1:
            findings.append(
                MovementFinding(
                    "m5_ambiguous_board_match",
                    f"Multiple Board expulsions have explicit iMIS ID {movement.subject_key}.",
                    movement.evidence,
                )
            )
        action_id = (
            movement.action_id
            if not operational
            else matches[0]
            if len(matches) == 1
            else None
        )
        visible = visible_by_id.get(action_id, ()) if action_id else ()
        latest = visible[-1] if visible else None
        proposed, approved, board_recorded = _board_dates(visible)
        completed.append(
            M5ExpulsionRow(
                movement.subject_key,
                action_id,
                latest.status.value if latest else "operational",
                proposed or movement.proposed_date,
                approved or movement.approved_date,
                movement.effective_date,
                movement.recorded_date
                if operational
                else board_recorded or movement.recorded_date,
                movements.report_cutoff,
                "recorded" if operational else "not_recorded",
                _board_refs(visible) if visible else movement.source_document_ref or "",
                _refs(movement),
                movement.date_basis,
            )
        )

    operational_count = sum(row.operational_history == "recorded" for row in completed)
    balance_count = movements.operational_balance.overall.movements["expelled"]
    if operational_count != balance_count:
        findings.append(
            MovementFinding(
                "m5_balance_count_difference",
                f"{operational_count} operational M5 rows versus {balance_count} expelled balance movements.",
            )
        )
    if len(completed) != len(classified):
        findings.append(
            MovementFinding(
                "m5_classified_count_difference",
                f"{len(completed)} completed rows versus {len(classified)} counted M5 expulsions.",
            )
        )
    opening = {
        decision.action_id
        for decision in movements.opening_board_view.decisions
        if decision.disposition == "applied"
    }
    applied = {
        decision.action_id
        for decision in movements.closing_board_view.decisions
        if decision.disposition == "applied"
        and decision.action_id not in opening
        and decision.action_id in visible_by_id
    }
    board_only_ids = {
        row.action_id for row in completed if row.operational_history == "not_recorded"
    }
    if board_only_ids != applied:
        findings.append(
            MovementFinding(
                "m5_board_decision_difference",
                f"Board-only M5 actions {sorted(board_only_ids)} differ from newly applied Board expulsion decisions {sorted(applied)}.",
            )
        )
    if not movements.operational_balance.overall.complete:
        findings.append(
            MovementFinding(
                "m5_incomplete_balance",
                "The operational balance is incomplete; confirmed M5 rows remain visible.",
            )
        )
    pending.sort(key=lambda row: (row.proposed_date or date.min, row.action_id or ""))
    completed.sort(key=lambda row: (row.effective_date or date.min, row.subject_key))
    return M5Expulsions(
        tuple(pending),
        tuple(completed),
        {"pending_proposals": len(pending), "completed_expulsions": len(completed)},
        tuple(findings),
    )


def write_m5_csv(result: M5Expulsions, output_dir: str | Path) -> tuple[Path, Path]:
    """Write pending proposals and completed expulsions as two CSV files."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths = (
        directory / "m5_pending_proposals.csv",
        directory / "m5_completed_expulsions.csv",
    )
    for path, rows in zip(
        paths, (result.pending_proposals, result.completed_expulsions), strict=True
    ):
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(
                file, fieldnames=[field.name for field in fields(M5ExpulsionRow)]
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(asdict(row))
    return paths
