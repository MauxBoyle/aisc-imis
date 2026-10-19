"""Select source-backed M4 movements and write separate CSV lists."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, fields
from datetime import date
from pathlib import Path

from aisc_imis.evidence_ledger import CandidateLifecycleEvent
from aisc_imis.lifecycle_period_movements import MovementFinding
from aisc_imis.quarterly_board_movements import (
    QuarterlyMovementResult,
    QuarterlyMovementRow,
)


@dataclass(frozen=True)
class M4MovementRow:
    subject_key: str
    action: str
    effective_date: date
    recorded_date: date | None
    report_cutoff: date
    category: str | None
    member_type: str | None
    operational_status: str
    ledger_evidence_refs: str
    date_basis: str = "event_effective_date"


@dataclass(frozen=True)
class M4ResignationsReinstatements:
    resignations: tuple[M4MovementRow, ...]
    reinstatements: tuple[M4MovementRow, ...]
    counts: dict[str, int]
    findings: tuple[MovementFinding, ...]


def _evidence_refs(movement: QuarterlyMovementRow) -> str:
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


def build_m4_resignations_reinstatements(
    movements: QuarterlyMovementResult,
) -> M4ResignationsReinstatements:
    """Select counted M4 state changes from one classified quarter.

    The classifier determines which evidence is known by the report cutoff.
    Inconsistencies stay visible as findings; no balancing row is added.
    """
    rows: dict[str, list[M4MovementRow]] = {"resigned": [], "reinstated": []}
    findings = list(movements.findings)
    classified = {action: 0 for action in rows}
    seen: set[tuple[str, str, date]] = set()
    for movement in movements.counted:
        if movement.measure != "M4" or movement.action not in rows:
            continue
        classified[movement.action] += 1
        key = (movement.subject_key, movement.action, movement.effective_date)
        if key in seen:
            findings.append(
                MovementFinding(
                    "duplicate_classified_m4_action",
                    f"Repeated counted {movement.action} for {movement.subject_key} on {movement.effective_date}.",
                    movement.evidence,
                )
            )
            continue
        seen.add(key)
        if not any(
            isinstance(entry.record, CandidateLifecycleEvent)
            and entry.record.event_name == movement.action
            for entry in movement.evidence
        ):
            findings.append(
                MovementFinding(
                    "m4_missing_state_change_evidence",
                    f"Counted {movement.action} for {movement.subject_key} lacks matching lifecycle evidence.",
                    movement.evidence,
                )
            )
            continue
        rows[movement.action].append(
            M4MovementRow(
                movement.subject_key,
                movement.action,
                movement.effective_date,
                movement.recorded_date,
                movements.report_cutoff,
                movement.category,
                movement.member_type,
                "former_member" if movement.action == "resigned" else "current_member",
                _evidence_refs(movement),
                movement.date_basis,
            )
        )

    for action in rows:
        rows[action].sort(key=lambda row: (row.effective_date, row.subject_key))
        actual = len(rows[action])
        if actual != classified[action]:
            findings.append(
                MovementFinding(
                    "m4_classified_count_difference",
                    f"{action}: {actual} exported rows versus {classified[action]} counted M4 actions.",
                )
            )
        balance_count = movements.operational_balance.overall.movements[action]
        if actual != balance_count:
            findings.append(
                MovementFinding(
                    "m4_balance_count_difference",
                    f"{action}: {actual} exported rows versus {balance_count} operational balance movements.",
                )
            )
    return M4ResignationsReinstatements(
        tuple(rows["resigned"]),
        tuple(rows["reinstated"]),
        {action: len(items) for action, items in rows.items()},
        tuple(findings),
    )


def write_m4_csv(
    result: M4ResignationsReinstatements, output_dir: str | Path
) -> tuple[Path, Path]:
    """Write the two M4 lists under a caller-chosen directory."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths = (directory / "m4_resignations.csv", directory / "m4_reinstatements.csv")
    columns = [field.name for field in fields(M4MovementRow)]
    for path, rows in zip(
        paths, (result.resignations, result.reinstatements), strict=True
    ):
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow(asdict(row))
    return paths
