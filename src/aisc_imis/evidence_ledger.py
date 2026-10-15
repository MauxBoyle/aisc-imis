"""Immutable, provenance-rich records for membership evidence ledgers.

This module deliberately stores evidence without deciding which record is more
credible.  In particular, it does not join subjects, rank sources, infer a
lifecycle rule, or remove contradictory records.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from aisc_imis.normalization_contracts import SourceReference

type DateValue = date | datetime
"""A calendar date or a timestamp; timestamps retain their time precision."""


class InterpretationStatus(StrEnum):
    """How firmly a record's stated meaning has been established."""

    VERIFIED = "verified"
    INFERRED = "inferred"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class ObservedFact:
    """One source-backed value observed for a subject.

    This is an observation, not a claim that the value caused a lifecycle
    event.  Its source is retained as supplied by the source adapter.
    """

    subject_key: str
    fact_name: str
    fact_value: str
    source_reference: SourceReference
    effective_date: DateValue | None = None
    recorded_date: DateValue | None = None
    observed_date: DateValue | None = None
    interpretation_status: InterpretationStatus = InterpretationStatus.VERIFIED

    def __post_init__(self) -> None:
        _validate_text("subject_key", self.subject_key)
        _validate_text("fact_name", self.fact_name)
        _validate_source(self.source_reference)
        _validate_dates(self.effective_date, self.recorded_date, self.observed_date)
        _validate_status(self.interpretation_status)


@dataclass(frozen=True)
class CandidateLifecycleEvent:
    """A derived, reviewable lifecycle-event candidate.

    Derived candidates must cite at least one source row and state why the
    interpretation was made.  The class does not make that interpretation
    correct; ``interpretation_status`` records its review state.
    """

    subject_key: str
    event_name: str
    source_references: tuple[SourceReference, ...]
    interpretation_reason: str
    effective_date: DateValue | None = None
    recorded_date: DateValue | None = None
    observed_date: DateValue | None = None
    interpretation_status: InterpretationStatus = InterpretationStatus.INFERRED

    def __post_init__(self) -> None:
        _validate_text("subject_key", self.subject_key)
        _validate_text("event_name", self.event_name)
        if not self.source_references:
            raise ValueError("Candidate lifecycle events require at least one source.")
        for source_reference in self.source_references:
            _validate_source(source_reference)
        _validate_text("interpretation_reason", self.interpretation_reason)
        _validate_dates(self.effective_date, self.recorded_date, self.observed_date)
        _validate_status(self.interpretation_status)


@dataclass(frozen=True)
class SnapshotStateObservation:
    """A state observed in a snapshot, without an implied transition."""

    subject_key: str
    state_name: str
    source_reference: SourceReference
    effective_date: DateValue | None = None
    recorded_date: DateValue | None = None
    observed_date: DateValue | None = None
    interpretation_status: InterpretationStatus = InterpretationStatus.VERIFIED

    def __post_init__(self) -> None:
        _validate_text("subject_key", self.subject_key)
        _validate_text("state_name", self.state_name)
        _validate_source(self.source_reference)
        _validate_dates(self.effective_date, self.recorded_date, self.observed_date)
        _validate_status(self.interpretation_status)


type LedgerRecord = ObservedFact | CandidateLifecycleEvent | SnapshotStateObservation

_DATE_COLUMNS = ("effective_date", "recorded_date", "observed_date")
_RECORD_TYPES = {
    "observed_fact": ObservedFact,
    "candidate_lifecycle_event": CandidateLifecycleEvent,
    "snapshot_state_observation": SnapshotStateObservation,
}


def to_tabular_rows(records: Iterable[LedgerRecord]) -> tuple[dict[str, str], ...]:
    """Serialize records as rows in the one typed evidence-ledger table.

    The rows are suitable for a CSV or spreadsheet export.  Every row includes
    a stable ``record_type`` and every citation is JSON in
    ``source_references``.  This function preserves input order, including
    contradictory records.
    """
    return tuple(_record_to_row(record) for record in records)


def from_tabular_rows(rows: Iterable[Mapping[str, str]]) -> tuple[LedgerRecord, ...]:
    """Restore typed records from :func:`to_tabular_rows` output.

    ``ValueError`` identifies malformed values, unknown record types, invalid
    statuses, and invalid ISO date/time strings instead of guessing a meaning.
    """
    restored: list[LedgerRecord] = []
    for index, row in enumerate(rows, start=1):
        try:
            restored.append(_row_to_record(row))
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"Invalid evidence-ledger row {index}: {error}") from error
    return tuple(restored)


def _record_to_row(record: LedgerRecord) -> dict[str, str]:
    row = {
        "subject_key": record.subject_key,
        "effective_date": _format_date(record.effective_date),
        "recorded_date": _format_date(record.recorded_date),
        "observed_date": _format_date(record.observed_date),
        "interpretation_status": record.interpretation_status.value,
    }
    if isinstance(record, ObservedFact):
        return {
            "record_type": "observed_fact",
            **row,
            "fact_name": record.fact_name,
            "fact_value": record.fact_value,
            "source_references": _format_sources((record.source_reference,)),
            "event_name": "",
            "state_name": "",
            "interpretation_reason": "",
        }
    if isinstance(record, CandidateLifecycleEvent):
        return {
            "record_type": "candidate_lifecycle_event",
            **row,
            "fact_name": "",
            "fact_value": "",
            "source_references": _format_sources(record.source_references),
            "event_name": record.event_name,
            "state_name": "",
            "interpretation_reason": record.interpretation_reason,
        }
    if isinstance(record, SnapshotStateObservation):
        return {
            "record_type": "snapshot_state_observation",
            **row,
            "fact_name": "",
            "fact_value": "",
            "source_references": _format_sources((record.source_reference,)),
            "event_name": "",
            "state_name": record.state_name,
            "interpretation_reason": "",
        }
    raise TypeError(f"Unsupported evidence-ledger record: {type(record).__name__}")


def _row_to_record(row: Mapping[str, str]) -> LedgerRecord:
    if not isinstance(row, Mapping):
        raise ValueError("row must be a mapping")
    record_type = _required(row, "record_type")
    if record_type not in _RECORD_TYPES:
        raise ValueError(f"unknown record_type {record_type!r}")
    status = _parse_status(_required(row, "interpretation_status"))
    dates = {column: _parse_date(row.get(column, ""), column) for column in _DATE_COLUMNS}
    sources = _parse_sources(_required(row, "source_references"))
    common = {
        "subject_key": _required(row, "subject_key"),
        **dates,
        "interpretation_status": status,
    }
    if record_type == "observed_fact":
        if len(sources) != 1:
            raise ValueError("observed_fact requires exactly one source reference")
        return ObservedFact(
            **common,
            fact_name=_required(row, "fact_name"),
            fact_value=_required_value(row, "fact_value"),
            source_reference=sources[0],
        )
    if record_type == "candidate_lifecycle_event":
        return CandidateLifecycleEvent(
            **common,
            event_name=_required(row, "event_name"),
            source_references=sources,
            interpretation_reason=_required(row, "interpretation_reason"),
        )
    if len(sources) != 1:
        raise ValueError("snapshot_state_observation requires exactly one source reference")
    return SnapshotStateObservation(
        **common,
        state_name=_required(row, "state_name"),
        source_reference=sources[0],
    )


def _format_date(value: DateValue | None) -> str:
    return "" if value is None else value.isoformat()


def _parse_date(value: object, column: str) -> DateValue | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError(f"{column} must be an ISO date/time string")
    try:
        if "T" in value or " " in value:
            return datetime.fromisoformat(value)
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{column} is not an ISO date/time value: {value!r}") from error


def _format_sources(sources: tuple[SourceReference, ...]) -> str:
    return json.dumps(
        [
            {"source_name": source.source_name, "row_reference": source.row_reference}
            for source in sources
        ],
        separators=(",", ":"),
    )


def _parse_sources(value: object) -> tuple[SourceReference, ...]:
    if not isinstance(value, str):
        raise ValueError("source_references must be JSON text")
    decoded = json.loads(value)
    if not isinstance(decoded, list):
        raise ValueError("source_references must encode a JSON array")
    references: list[SourceReference] = []
    for item in decoded:
        if not isinstance(item, dict):
            raise ValueError("each source reference must be a JSON object")
        source_name = item.get("source_name")
        row_reference = item.get("row_reference")
        if not isinstance(source_name, str) or not isinstance(row_reference, str):
            raise ValueError("each source reference needs text source_name and row_reference")
        references.append(SourceReference(source_name, row_reference))
    return tuple(references)


def _required(row: Mapping[str, str], column: str) -> str:
    value = row.get(column)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{column} is required and must be nonblank text")
    return value


def _required_value(row: Mapping[str, str], column: str) -> str:
    value = row.get(column)
    if not isinstance(value, str):
        raise ValueError(f"{column} is required and must be text")
    return value


def _parse_status(value: str) -> InterpretationStatus:
    try:
        return InterpretationStatus(value)
    except ValueError as error:
        raise ValueError(f"unknown interpretation_status {value!r}") from error


def _validate_text(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonblank text")


def _validate_source(value: object) -> None:
    if not isinstance(value, SourceReference):
        raise ValueError("source_reference must be a SourceReference")


def _validate_dates(*values: DateValue | None) -> None:
    for value in values:
        if value is not None and not isinstance(value, (date, datetime)):
            raise ValueError("date fields must be date, datetime, or None")


def _validate_status(value: object) -> None:
    if not isinstance(value, InterpretationStatus):
        raise ValueError("interpretation_status must be an InterpretationStatus")
