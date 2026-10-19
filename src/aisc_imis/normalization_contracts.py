"""Lossless contracts for membership-source rows.

This module only checks that a row has the minimum fields needed to describe
its source shape.  It intentionally does not create subject keys, join rows,
interpret codes, parse dates, or resolve conflicting evidence.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceReference:
    """A caller-provided pointer to the source row, kept exactly as supplied."""

    source_name: str
    row_reference: str


@dataclass(frozen=True)
class RawField:
    """One source column and its unmodified CSV-style value."""

    name: str
    value: str | None


@dataclass(frozen=True)
class ValidationFailure:
    """A single reason a row cannot produce a normalized record."""

    field: str
    code: str
    message: str


@dataclass(frozen=True)
class ValidationRejection:
    """An unaccepted row and every validation failure found in it."""

    reference: SourceReference
    raw_fields: tuple[RawField, ...]
    failures: tuple[ValidationFailure, ...]

    def raw_value(self, name: str) -> str | None:
        """Return an original field value, or ``None`` when the column is absent."""
        return next(
            (field.value for field in self.raw_fields if field.name == name), None
        )


@dataclass(frozen=True)
class EvidenceRecord:
    """Common immutable provenance and raw evidence for accepted records."""

    reference: SourceReference
    raw_fields: tuple[RawField, ...]

    def raw_value(self, name: str) -> str | None:
        """Return an original field value, or ``None`` when the column is absent."""
        return next(
            (field.value for field in self.raw_fields if field.name == name), None
        )


@dataclass(frozen=True)
class CurrentRecord(EvidenceRecord):
    """A row from the current-state export."""

    imis_id: str
    member_type: str
    is_company: str
    is_member: str
    last_updated: str
    status: str | None
    category: str | None


@dataclass(frozen=True)
class SnapshotObservation(EvidenceRecord):
    """A row from the historical snapshot export; not inferred history."""

    imis_id: str
    member_type: str
    is_company: str
    is_member: str
    last_updated: str
    status: str | None
    category: str | None


@dataclass(frozen=True)
class MembershipChange(EvidenceRecord):
    """A membership-change transaction without an inferred event meaning."""

    change_id: str
    ordinal: str
    change_type: str
    member_type: str
    change_update: str
    change_created: str
    status: str
    change_effective: str | None
    category: str | None


@dataclass(frozen=True)
class ActivityRecord(EvidenceRecord):
    """An activity transaction without an inferred lifecycle meaning."""

    imis_id: str
    sequence: str
    transaction: str
    activity_type: str
    effective_date: str | None
    member_type: str
    is_company: str
    transaction_date: str | None


Record = CurrentRecord | SnapshotObservation | MembershipChange | ActivityRecord


@dataclass(frozen=True)
class BatchValidationResult:
    """Every accepted record and rejection, in their original input order per group."""

    accepted: tuple[Record, ...]
    rejected: tuple[ValidationRejection, ...]


SourceRow = Mapping[str, str | None]


def validate_current_record(
    row: SourceRow, reference: SourceReference
) -> CurrentRecord | ValidationRejection:
    """Validate one current-state row without changing its values."""
    required = ("iMIS Id", "Member Type", "Is Company", "Is Member", "Last Updated")
    rejection = _rejection_if_invalid(row, reference, required)
    if rejection:
        return rejection
    return CurrentRecord(
        reference,
        _raw_fields(row),
        row["iMIS Id"],
        row["Member Type"],
        row["Is Company"],
        row["Is Member"],
        row["Last Updated"],
        _optional(row, "Status"),
        _optional(row, "Category"),
    )


def validate_snapshot_observation(
    row: SourceRow, reference: SourceReference
) -> SnapshotObservation | ValidationRejection:
    """Validate one historical snapshot row without sorting or reconciling it."""
    required = ("iMIS Id", "Member Type", "Is Company", "Is Member", "Last Updated")
    rejection = _rejection_if_invalid(row, reference, required)
    if rejection:
        return rejection
    return SnapshotObservation(
        reference,
        _raw_fields(row),
        row["iMIS Id"],
        row["Member Type"],
        row["Is Company"],
        row["Is Member"],
        row["Last Updated"],
        _optional(row, "Status"),
        _optional(row, "Category"),
    )


def validate_membership_change(
    row: SourceRow, reference: SourceReference
) -> MembershipChange | ValidationRejection:
    """Validate one change row without interpreting its change type."""
    required = (
        "ChangeID",
        "Ordinal",
        "Change Type",
        "Member Type",
        "ChangeUpdate",
        "ChangeCreated",
        "Status",
    )
    rejection = _rejection_if_invalid(row, reference, required)
    if rejection:
        return rejection
    return MembershipChange(
        reference,
        _raw_fields(row),
        row["ChangeID"],
        row["Ordinal"],
        row["Change Type"],
        row["Member Type"],
        row["ChangeUpdate"],
        row["ChangeCreated"],
        row["Status"],
        _optional(row, "ChangeEffective"),
        _optional(row, "Category"),
    )


def validate_activity_record(
    row: SourceRow, reference: SourceReference
) -> ActivityRecord | ValidationRejection:
    """Validate one activity row without assigning business meaning to it."""
    required = (
        "iMIS Id",
        "Sequence",
        "A_Transaction",
        "Activity Type",
        "Member Type",
        "Is a Company",
    )
    if not _has_text(row.get("Transaction Date")):
        required = (*required, "Effective Date")
    rejection = _rejection_if_invalid(row, reference, required)
    if rejection:
        return rejection
    return ActivityRecord(
        reference,
        _raw_fields(row),
        row["iMIS Id"],
        row["Sequence"],
        row["A_Transaction"],
        row["Activity Type"],
        _optional(row, "Effective Date"),
        row["Member Type"],
        row["Is a Company"],
        _optional(row, "Transaction Date"),
    )


def validate_current_records(
    rows: Iterable[tuple[SourceReference, SourceRow]],
) -> BatchValidationResult:
    """Validate current rows, retaining both valid records and rejected input rows."""
    return _validate_batch(rows, validate_current_record)


def validate_snapshot_observations(
    rows: Iterable[tuple[SourceReference, SourceRow]],
) -> BatchValidationResult:
    """Validate snapshot rows, retaining their supplied order."""
    return _validate_batch(rows, validate_snapshot_observation)


def validate_membership_changes(
    rows: Iterable[tuple[SourceReference, SourceRow]],
) -> BatchValidationResult:
    """Validate membership changes, retaining their supplied order."""
    return _validate_batch(rows, validate_membership_change)


def validate_activity_records(
    rows: Iterable[tuple[SourceReference, SourceRow]],
) -> BatchValidationResult:
    """Validate activity rows, retaining their supplied order."""
    return _validate_batch(rows, validate_activity_record)


def _validate_batch(
    rows: Iterable[tuple[SourceReference, SourceRow]],
    validator: Callable[[SourceRow, SourceReference], Record | ValidationRejection],
) -> BatchValidationResult:
    accepted: list[Record] = []
    rejected: list[ValidationRejection] = []
    for reference, row in rows:
        outcome = validator(row, reference)
        if isinstance(outcome, ValidationRejection):
            rejected.append(outcome)
        else:
            accepted.append(outcome)
    return BatchValidationResult(tuple(accepted), tuple(rejected))


def _rejection_if_invalid(
    row: SourceRow, reference: SourceReference, required: tuple[str, ...]
) -> ValidationRejection | None:
    failures = tuple(
        ValidationFailure(
            field, "required", f"{field} is required and cannot be blank."
        )
        for field in required
        if not _has_text(row.get(field))
    )
    if failures:
        return ValidationRejection(reference, _raw_fields(row), failures)
    return None


def _raw_fields(row: SourceRow) -> tuple[RawField, ...]:
    return tuple(RawField(name, value) for name, value in row.items())


def _has_text(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _optional(row: SourceRow, field: str) -> str | None:
    value = row.get(field)
    return value if _has_text(value) else None
