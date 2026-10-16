"""Build M2 and M3 display rows from classified joins and an IQA extract."""

from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, fields
from datetime import date
from pathlib import Path

from aisc_imis.board_pending_actions import (
    ActionKind,
    ActionRevision,
    BoardPendingActions,
)
from aisc_imis.quarterly_board_movements import (
    QuarterlyMovementResult,
    QuarterlyMovementRow,
)

IQA_COLUMNS = (
    "Join Date",
    "Member Type",
    "iMIS Id",
    "Company",
    "Full Address",
    "Category",
    "Tonnage Est",
    "Reference Contact",
    "Reference Company",
)


@dataclass(frozen=True)
class NewMemberIqaRow:
    join_date: str
    member_type: str
    imis_id: str
    company: str
    full_address: str
    category: str
    tonnage_est: str
    reference_contact: str
    reference_company: str
    source_file: str
    source_row: int


@dataclass(frozen=True)
class NewMemberFinding:
    code: str
    imis_id: str
    message: str
    source_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class NewMemberRow:
    measure: str
    imis_id: str
    member_type: str
    operational_status: str
    board_action_status: str
    proposed_date: date | None
    approved_date: date | None
    effective_date: date
    recorded_date: date | None
    report_cutoff: date
    join_date: str
    company: str
    full_address: str
    category: str
    tonnage_est: str
    reference_contact: str
    reference_company: str
    lifecycle_evidence_refs: str
    board_evidence_ref: str
    iqa_source_refs: str


@dataclass(frozen=True)
class M2M3NewMembers:
    m2: tuple[NewMemberRow, ...]
    m3: tuple[NewMemberRow, ...]
    findings: tuple[NewMemberFinding, ...]
    counts: dict[str, int]


def read_new_members_iqa(path: str | Path) -> tuple[NewMemberIqaRow, ...]:
    """Read the CsContact/FirmInfo IQA fields, keeping IDs and dates as text."""
    source = Path(path)
    with source.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        missing = set(IQA_COLUMNS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"IQA export is missing columns: {sorted(missing)}")
        rows = []
        for number, raw in enumerate(reader, start=2):
            if None in raw:
                raise ValueError(f"IQA row {number} has extra columns.")
            values = [raw[column] for column in IQA_COLUMNS]
            if any(value is None for value in values):
                raise ValueError(f"IQA row {number} has missing columns.")
            rows.append(
                NewMemberIqaRow(
                    *(value.strip() for value in values),
                    str(source),
                    number,
                )
            )
    return tuple(rows)


def _iqa_ref(row: NewMemberIqaRow) -> str:
    return f"{row.source_file}:{row.source_row}"


def _matching_board_actions(
    key: str, board_actions: BoardPendingActions, cutoff: date
) -> list[tuple[str, tuple[ActionRevision, ...]]]:
    matches = []
    for action in board_actions.actions:
        if action.kind is not ActionKind.NEW_MEMBER_APPROVAL:
            continue
        visible = [
            revision for revision in action.revisions if revision.status_date <= cutoff
        ]
        if not visible:
            continue
        explicit_ids = {revision.imis_id for revision in visible if revision.imis_id}
        if (key in explicit_ids) or (not explicit_ids and action.member_ref == key):
            matches.append((action.action_id, tuple(visible)))
    return matches


def _lifecycle_refs(movement: QuarterlyMovementRow) -> str:
    refs = set()
    for entry in movement.evidence:
        refs.add(f"ledger:{entry.record_id}")
        record = entry.record
        sources = getattr(record, "source_references", None)
        if sources is None:
            sources = (record.source_reference,)
        refs.update(
            f"{source.source_name}:{source.row_reference}" for source in sources
        )
    return "; ".join(sorted(refs))


def build_m2_m3_new_members(
    movements: QuarterlyMovementResult,
    iqa_rows: Iterable[NewMemberIqaRow],
    board_actions: BoardPendingActions,
) -> M2M3NewMembers:
    """Select classified ACT/ASSOC joins, then attach exact-ID IQA details.

    IQA Join Date is display evidence only. A missing or conflicting IQA match
    leaves the classified join present with blank display fields.
    """
    by_id: dict[str, list[NewMemberIqaRow]] = defaultdict(list)
    for row in iqa_rows:
        by_id[row.imis_id].append(row)
    findings: list[NewMemberFinding] = []
    output: dict[str, list[NewMemberRow]] = {"M2": [], "M3": []}
    expected = {"M2": 0, "M3": 0}
    seen: set[tuple[str, str, date]] = set()
    for movement in movements.counted:
        if movement.action != "joined" or movement.member_type not in {"ACT", "ASSOC"}:
            continue
        measure = "M2" if movement.member_type == "ACT" else "M3"
        if movement.measure != measure:
            raise ValueError(
                f"Classified join {movement.subject_key} has inconsistent measure."
            )
        expected[measure] += 1
        key = (movement.subject_key, measure, movement.effective_date)
        if key in seen:
            findings.append(
                NewMemberFinding(
                    "duplicate_classified_join",
                    movement.subject_key,
                    "More than one counted join has the same ID, measure, and effective date.",
                )
            )
        seen.add(key)
        matches = by_id.get(movement.subject_key, [])
        refs = tuple(_iqa_ref(row) for row in matches)
        unique = {
            tuple(getattr(row, field.name) for field in fields(NewMemberIqaRow)[:9])
            for row in matches
        }
        if not matches:
            findings.append(
                NewMemberFinding(
                    "missing_iqa_match",
                    movement.subject_key,
                    "Classified join has no exact iMIS ID match in the IQA extract.",
                )
            )
        elif len(unique) > 1:
            findings.append(
                NewMemberFinding(
                    "conflicting_iqa_matches",
                    movement.subject_key,
                    "Exact-ID IQA rows disagree; display fields are blank pending review.",
                    refs,
                )
            )
        elif len(matches) > 1:
            findings.append(
                NewMemberFinding(
                    "duplicate_iqa_match",
                    movement.subject_key,
                    "Identical exact-ID IQA rows were retained as source references.",
                    refs,
                )
            )
        iqa = matches[0] if len(unique) == 1 else None
        if iqa:
            if iqa.member_type != movement.member_type:
                findings.append(
                    NewMemberFinding(
                        "iqa_member_type_disagreement",
                        movement.subject_key,
                        "IQA Member Type differs from the classified join Member Type.",
                        refs,
                    )
                )
            for column, value in zip(IQA_COLUMNS, unique.pop(), strict=True):
                if not value:
                    findings.append(
                        NewMemberFinding(
                            "missing_iqa_field",
                            movement.subject_key,
                            f"Matched IQA row has blank {column}.",
                            refs,
                        )
                    )

        board_matches = _matching_board_actions(
            movement.subject_key, board_actions, movements.report_cutoff
        )
        if len(board_matches) > 1:
            findings.append(
                NewMemberFinding(
                    "conflicting_board_actions",
                    movement.subject_key,
                    "Multiple visible new-member Board actions share this iMIS ID.",
                    tuple(action_id for action_id, _ in board_matches),
                )
            )
        visible = board_matches[0][1] if len(board_matches) == 1 else ()
        board_revision = visible[-1] if visible else None
        board_status = board_revision.status.value if board_revision else ""
        proposed = next(
            (
                revision.status_date
                for revision in visible
                if revision.status.value == "proposed"
            ),
            None,
        )
        approved = next(
            (
                revision.status_date
                for revision in reversed(visible)
                if revision.status.value == "approved"
            ),
            None,
        )
        board_ref = (
            f"{board_matches[0][0]}:{board_revision.source_document_ref}"
            if board_revision
            else f"{movement.action_id}:{movement.source_document_ref}"
            if movement.action_id and movement.source_document_ref
            else ""
        )
        output[measure].append(
            NewMemberRow(
                measure=measure,
                imis_id=movement.subject_key,
                member_type=movement.member_type,
                operational_status="joined" if movement.evidence else "pending-iMIS",
                board_action_status=board_status,
                proposed_date=movement.proposed_date or proposed,
                approved_date=movement.approved_date or approved,
                effective_date=movement.effective_date,
                recorded_date=movement.recorded_date,
                report_cutoff=movements.report_cutoff,
                join_date=iqa.join_date if iqa else "",
                company=iqa.company if iqa else "",
                full_address=iqa.full_address if iqa else "",
                category=iqa.category if iqa else "",
                tonnage_est=iqa.tonnage_est if iqa else "",
                reference_contact=iqa.reference_contact if iqa else "",
                reference_company=iqa.reference_company if iqa else "",
                lifecycle_evidence_refs=_lifecycle_refs(movement),
                board_evidence_ref=board_ref,
                iqa_source_refs="; ".join(refs),
            )
        )
    m2 = tuple(sorted(output["M2"], key=lambda row: (row.effective_date, row.imis_id)))
    m3 = tuple(sorted(output["M3"], key=lambda row: (row.effective_date, row.imis_id)))
    if len(m2) != expected["M2"] or len(m3) != expected["M3"]:
        raise AssertionError(
            "M2/M3 rows do not reconcile to classified ACT/ASSOC joins."
        )
    return M2M3NewMembers(m2, m3, tuple(findings), expected)


def write_m2_m3_csv(
    result: M2M3NewMembers, output_dir: str | Path
) -> tuple[Path, Path]:
    """Write consistently ordered M2 and M3 CSV files to a chosen directory."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths = (directory / "m2_new_members.csv", directory / "m3_new_members.csv")
    columns = tuple(field.name for field in fields(NewMemberRow))
    for path, rows in zip(paths, (result.m2, result.m3), strict=True):
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow(asdict(row))
    return paths
