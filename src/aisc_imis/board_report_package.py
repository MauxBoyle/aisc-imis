"""Build a reproducible local M1–M5 Board report package."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import groupby
from pathlib import Path

from aisc_imis.activity_history_records import read_activity_history_records
from aisc_imis.board_pending_actions import load_board_pending_actions
from aisc_imis.current_member_records import read_current_member_records
from aisc_imis.evidence_conversion import (
    convert_activity_history_observations,
    convert_current_member_observations,
    convert_historical_snapshot_observations,
    convert_iqa_join_dates,
    convert_membership_change_observations,
)
from aisc_imis.evidence_ledger import SnapshotStateObservation
from aisc_imis.historical_snapshot_records import read_historical_snapshot_records
from aisc_imis.lifecycle_rules import load_lifecycle_rules
from aisc_imis.m1_membership_numbers import build_m1_membership_numbers, write_m1_csv
from aisc_imis.m4_resignations_reinstatements import (
    build_m4_resignations_reinstatements,
    write_m4_csv,
)
from aisc_imis.m5_expulsions import build_m5_expulsions, write_m5_csv
from aisc_imis.member_ledger import (
    build_member_evidence_ledger,
    write_member_evidence_csv,
)
from aisc_imis.member_state_reconciliation import (
    MembershipObservation,
    reconcile_member_states,
)
from aisc_imis.membership_change_records import read_membership_change_records
from aisc_imis.new_members import (
    build_m2_m3_new_members,
    read_new_members_iqa,
    write_m2_m3_csv,
)
from aisc_imis.quarterly_board_movements import classify_quarterly_movements
from aisc_imis.review_registry import annotate_findings, load_review_registry


@dataclass(frozen=True)
class BoardReportInputs:
    period_start: date
    as_of_date: date
    board_cutoff: date
    current_export_date: date
    current_csv: Path
    history_csv: Path
    membership_changes_csv: Path
    activity_history_csv: Path
    new_members_iqa_csv: Path
    board_actions_json: Path
    review_registry_json: Path
    reference_directory: Path
    output_directory: Path


@dataclass(frozen=True)
class BoardReportResult:
    run_id: str
    output_files: tuple[Path, ...]
    finding_count: int


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_rows(
    path: Path, columns: tuple[str, ...], rows: list[dict[str, str]]
) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _finding(
    source: str,
    code: str,
    message: str,
    subject: str = "",
    evidence: str = "",
    status: str = "unreviewed",
    review: str = "",
    finding_id: str = "",
    finding_type: str = "",
) -> dict[str, str]:
    return {
        "source": source,
        "code": code,
        "message": message,
        "subject_key": subject,
        "evidence_ids": evidence,
        "review_status": status,
        "review": review,
        "finding_id": finding_id,
        "finding_type": finding_type or source,
    }


def _calendar_day(value: date | datetime | None) -> date | None:
    return value.date() if isinstance(value, datetime) else value


def build_board_report_package(
    inputs: BoardReportInputs, progress: Callable[[str], None] | None = None
) -> BoardReportResult:
    """Read local evidence, run the existing builders, and write an audited package."""
    if inputs.period_start > inputs.as_of_date:
        raise ValueError("period start must be on or before the as-of date")
    if inputs.board_cutoff < inputs.as_of_date:
        raise ValueError("Board cutoff must cover the as-of date")
    if inputs.current_export_date > inputs.board_cutoff:
        raise ValueError("current export date must not exceed the Board cutoff")
    if inputs.as_of_date == date.max:
        raise ValueError("as-of date must allow a following exclusive end date")
    sources = {
        name: Path(getattr(inputs, name))
        for name in (
            "current_csv",
            "history_csv",
            "membership_changes_csv",
            "activity_history_csv",
            "new_members_iqa_csv",
            "board_actions_json",
            "review_registry_json",
        )
    }
    references = Path(inputs.reference_directory)
    for name, path in sources.items():
        if not path.is_file():
            raise FileNotFoundError(f"{name}: {path}")
    if not references.is_dir():
        raise FileNotFoundError(f"reference_directory: {references}")
    reference_files = sorted(path for path in references.rglob("*") if path.is_file())
    if progress:
        progress("Fingerprinting inputs")
    source_hashes = {name: {"sha256": _hash(path)} for name, path in sources.items()}
    source_hashes["reference_directory"] = {
        str(path.relative_to(references)): _hash(path) for path in reference_files
    }
    parameters = {
        "period_start": inputs.period_start.isoformat(),
        "as_of_date": inputs.as_of_date.isoformat(),
        "period_end_exclusive": (inputs.as_of_date + timedelta(days=1)).isoformat(),
        "board_cutoff": inputs.board_cutoff.isoformat(),
        "current_export_date": inputs.current_export_date.isoformat(),
    }
    rules = load_lifecycle_rules(references)
    first_rule_date = min(rule.effective_reporting_date for rule in rules.rules)
    if progress and inputs.as_of_date < first_rule_date:
        progress(
            f"Warning: lifecycle rules begin {first_rule_date}; "
            f"the {inputs.as_of_date} as-of balance may be unresolved"
        )
    findings: list[dict[str, str]] = []
    records = []
    historical_observations: tuple[MembershipObservation, ...] = ()
    current_observations: tuple[MembershipObservation, ...] = ()
    for name, path, reader, converter in (
        (
            "current",
            sources["current_csv"],
            read_current_member_records,
            convert_current_member_observations,
        ),
        (
            "history",
            sources["history_csv"],
            read_historical_snapshot_records,
            convert_historical_snapshot_observations,
        ),
        (
            "membership_changes",
            sources["membership_changes_csv"],
            read_membership_change_records,
            convert_membership_change_observations,
        ),
        (
            "activity_history",
            sources["activity_history_csv"],
            read_activity_history_records,
            convert_activity_history_observations,
        ),
    ):
        if progress:
            progress(f"Reading {name}")
        adapter = reader(path, references)
        for issue in adapter.findings:
            ref = issue.reference
            findings.append(
                _finding(
                    name,
                    issue.code,
                    issue.message,
                    evidence=f"{ref.source_name}:{ref.row_reference}" if ref else "",
                )
            )
        for rejection in adapter.rejections:
            findings.append(
                _finding(
                    name,
                    "rejected_source_row",
                    "Source row failed structural validation",
                    evidence=f"{rejection.reference.source_name}:{rejection.reference.row_reference}",
                )
            )
        if name == "current":
            current_observations = tuple(
                MembershipObservation.from_current(row) for row in adapter.observations
            )
            converted = converter(
                adapter.observations, export_date=inputs.current_export_date
            )
        elif name == "history":
            historical_observations = tuple(
                MembershipObservation.from_historical(row) for row in adapter.observations
            )
            converted = converter(adapter.observations)
        else:
            converted = converter(adapter.observations)
        records.extend(converted.records)
        for issue in converted.findings:
            findings.append(
                _finding(
                    "conversion",
                    issue.code,
                    issue.message,
                    evidence=f"{issue.reference.source_name}:{issue.reference.row_reference}",
                )
            )
        del adapter, converted
    if progress:
        progress("Building evidence ledger")
    iqa = read_new_members_iqa(sources["new_members_iqa_csv"])
    records.extend(convert_iqa_join_dates(iqa, inputs.current_export_date).records)
    ledger = build_member_evidence_ledger(records)
    del records
    board_actions = load_board_pending_actions(sources["board_actions_json"])
    registry = load_review_registry(sources["review_registry_json"])
    with (references / "categories.csv").open(newline="", encoding="utf-8-sig") as file:
        categories = tuple(row["code"] for row in csv.DictReader(file) if row["code"])
    if progress:
        progress("Calculating Board movements")
    period_end = inputs.as_of_date + timedelta(days=1)
    movement_entries = (
        entry for entry in ledger.entries
        if getattr(entry.record, "fact_name", None) == "join_date" or isinstance(entry.record, SnapshotStateObservation) or (
            (effective := _calendar_day(entry.record.effective_date)) is not None
            and effective < period_end
        ) or (
            (observed := _calendar_day(entry.record.observed_date)) is not None
            and observed < period_end
        )
    )
    movement = classify_quarterly_movements(
        movement_entries,
        inputs.period_start,
        period_end,
        inputs.board_cutoff,
        rules,
        board_actions,
        categories,
        join_measures={"ACT": "M2", "ASSOC": "M3"},
    )
    m1 = build_m1_membership_numbers(
        movement.operational_balance,
        movement.opening_board_view,
        movement.closing_board_view,
        inputs.board_cutoff,
    )
    m2m3 = build_m2_m3_new_members(movement, iqa, board_actions)
    m4 = build_m4_resignations_reinstatements(movement)
    m5 = build_m5_expulsions(movement, board_actions)
    if progress:
        progress("Reconciling member states")
    reconciliation = reconcile_member_states(
        ledger,
        historical_observations,
        current_observations,
        rules,
        current_export_date=inputs.current_export_date,
        snapshots_already_in_evidence=True,
    )
    del historical_observations, current_observations
    reviews = annotate_findings(
        reconciliation.findings, registry, as_of=inputs.board_cutoff
    )
    for annotation in reviews.findings:
        item = annotation.finding
        review = annotation.review
        findings.append(
            _finding(
                "reconciliation",
                item.code,
                item.scope,
                item.subject_key or "",
                "; ".join(
                    (*item.supporting_evidence_ids, *item.contradicting_evidence_ids)
                ),
                annotation.status.value,
                f"{review.reviewer}: {review.rationale}" if review else "",
                item.id,
                item.type.value,
            )
        )
    for item in reviews.unmatched_reviews:
        findings.append(
            _finding(
                "review_registry",
                "unmatched_review",
                item.scope,
                item.member_key or "",
                item.finding_id,
                "unmatched",
                item.rationale,
            )
        )
    for name, items in (
        ("movement", movement.findings),
        ("m4", m4.findings),
        ("m5", m5.findings),
    ):
        for item in items:
            findings.append(
                _finding(
                    name,
                    item.code,
                    item.message,
                    evidence="; ".join(
                        entry.record_id for entry in item.supporting_evidence
                    ),
                )
            )
    for item in m2m3.findings:
        findings.append(
            _finding(
                "m2_m3",
                item.code,
                item.message,
                item.imis_id,
                "; ".join(item.source_refs),
            )
        )
    for row in (m1.overall, *m1.categories.values()):
        if row.status != "reconciled":
            findings.append(
                _finding(
                    "m1",
                    row.status,
                    f"M1 balance status for {row.category or 'overall'}",
                    evidence=row.category or "overall",
                )
            )
    findings.sort(key=lambda row: tuple(row.values()))
    if progress:
        progress("Writing report files")
    output = Path(inputs.output_directory)
    output.mkdir(parents=True, exist_ok=True)
    paths = [output / "m1_membership_numbers.csv"]
    write_m1_csv(m1, paths[0])
    paths.extend(write_m2_m3_csv(m2m3, output))
    paths.extend(write_m4_csv(m4, output))
    paths.extend(write_m5_csv(m5, output))
    paths.append(write_member_evidence_csv(ledger, output / "member_evidence.csv"))
    drilldown = []
    ledger_groups = (
        (key, group)
        for key, group in groupby(ledger.entries, key=lambda entry: entry.record.subject_key)
    )
    ledger_group = next(ledger_groups, None)
    for member in movement.movement.contributors:
        while ledger_group is not None and ledger_group[0] < member.subject_key:
            ledger_group = next(ledger_groups, None)
        member_entries = (
            tuple(ledger_group[1])
            if ledger_group is not None and ledger_group[0] == member.subject_key
            else ()
        )
        drilldown.append(
            {
                "subject_key": member.subject_key,
                "opening_countability": member.opening_countability.value,
                "closing_countability": member.closing_countability.value,
                "opening_category": member.opening_category or "",
                "closing_category": member.closing_category or "",
                "lifecycle_actions": "; ".join(member.lifecycle_actions),
                "evidence_ids": "; ".join(
                    entry.record_id for entry in member_entries
                ),
            }
        )
    drill_path = output / "member_drilldown.csv"
    _write_rows(
        drill_path,
        (
            "subject_key",
            "opening_countability",
            "closing_countability",
            "opening_category",
            "closing_category",
            "lifecycle_actions",
            "evidence_ids",
        ),
        drilldown,
    )
    paths.append(drill_path)
    finding_path = output / "findings.csv"
    _write_rows(
        finding_path,
        (
            "source",
            "code",
            "message",
            "subject_key",
            "evidence_ids",
            "review_status",
            "review",
            "finding_id",
            "finding_type",
        ),
        findings,
    )
    paths.append(finding_path)
    identity = {
        "parameters": parameters,
        "inputs": source_hashes,
        "rule_versions": sorted({rule.rule_version for rule in rules.rules}),
    }
    run_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest = {
        **parameters,
        "run_id": run_id,
        "rule_versions": identity["rule_versions"],
        "inputs": source_hashes,
        "outputs": {path.name: _hash(path) for path in sorted(paths)},
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    paths.append(manifest_path)
    return BoardReportResult(run_id, tuple(paths), len(findings))
