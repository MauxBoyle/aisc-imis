"""Deterministic, member-focused views of immutable evidence-ledger records.

This module groups records only by the ``subject_key`` already supplied by a
caller.  It intentionally does not decide whether two identifiers are the same
member, select a preferred source, or interpret a sequence as a lifecycle.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from aisc_imis.evidence_ledger import LedgerRecord, to_tabular_rows

TABULAR_COLUMNS = (
    "record_type",
    "subject_key",
    "effective_date",
    "recorded_date",
    "observed_date",
    "interpretation_status",
    "fact_name",
    "fact_value",
    "source_references",
    "event_name",
    "state_name",
    "interpretation_reason",
    "member_type",
    "category",
)
"""The existing typed-ledger columns, in their deterministic export order."""

CSV_COLUMNS = ("record_id", *TABULAR_COLUMNS)
"""Columns written by :func:`write_member_evidence_csv`."""


@dataclass(frozen=True)
class MemberLedgerEntry:
    """One immutable record together with its deterministic content ID."""

    record_id: str
    record: LedgerRecord


@dataclass(frozen=True)
class MemberEvidenceLedger:
    """An immutable, ordered collection of evidence grouped by member key."""

    entries: tuple[MemberLedgerEntry, ...]
    member_keys: tuple[str, ...]

    def entries_for(self, subject_key: str) -> tuple[MemberLedgerEntry, ...]:
        """Return every retained entry for one already-confirmed member key."""
        return tuple(
            entry for entry in self.entries if entry.record.subject_key == subject_key
        )

    def records_for(self, subject_key: str) -> tuple[LedgerRecord, ...]:
        """Return every retained typed record for one already-confirmed member key."""
        return tuple(entry.record for entry in self.entries_for(subject_key))


def build_member_evidence_ledger(
    records: Iterable[LedgerRecord],
) -> MemberEvidenceLedger:
    """Build a deterministic view without dropping, joining, or ranking evidence.

    Each ``record_id`` is the SHA-256 digest of the record's canonical typed
    table row. Identical source evidence therefore has an identical ID, but is
    still retained as a separate entry. Records are grouped by their supplied
    ``subject_key`` and sorted by effective, recorded, and observed date.
    Missing dates sort last for each date role.
    """
    typed_records = tuple(records)
    entries = tuple(
        MemberLedgerEntry(record_id=_record_id(row), record=record)
        for record, row in zip(
            typed_records, to_tabular_rows(typed_records), strict=True
        )
    )
    ordered_entries = tuple(
        sorted(
            entries,
            key=lambda entry: (
                entry.record.subject_key,
                *_date_sort_key(entry.record),
                entry.record_id,
            ),
        )
    )
    return MemberEvidenceLedger(
        entries=ordered_entries,
        member_keys=tuple(
            sorted({entry.record.subject_key for entry in ordered_entries})
        ),
    )


def write_member_evidence_csv(
    ledger: MemberEvidenceLedger, output_path: str | Path
) -> Path:
    """Write a local CSV export to an explicit path and return that path.

    Parent directories are created when needed. The caller chooses the path;
    operational exports normally belong under ignored ``data/processed/``.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as export_file:
        writer = csv.DictWriter(export_file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for entry in ledger.entries:
            row = to_tabular_rows((entry.record,))[0]
            writer.writerow({"record_id": entry.record_id, **row})
    return path


def _record_id(row: dict[str, str]) -> str:
    """Create a content ID from values in a fixed typed-ledger column order."""
    # Keep IDs for pre-extension evidence stable.  New optional event evidence
    # participates in the ID only when supplied, so it cannot collide with an
    # otherwise identical older event.
    columns = list(TABULAR_COLUMNS)
    while columns[-1] in {"member_type", "category"} and not row[columns[-1]]:
        columns.pop()
    canonical_row = json.dumps(
        [row[column] for column in columns],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_row.encode("utf-8")).hexdigest()


def _date_sort_key(record: LedgerRecord) -> tuple[tuple[bool, str], ...]:
    """Sort ISO source values directly, preserving date versus timestamp precision."""
    return tuple(
        (value is None, "" if value is None else value.isoformat())
        for value in (record.effective_date, record.recorded_date, record.observed_date)
    )
