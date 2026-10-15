"""Tests for lossless, source-only normalization contracts."""

import json
from pathlib import Path

import pytest

from aisc_imis.normalization_contracts import (
    ActivityRecord,
    CurrentRecord,
    MembershipChange,
    SnapshotObservation,
    SourceReference,
    validate_activity_record,
    validate_current_record,
    validate_current_records,
    validate_membership_change,
    validate_snapshot_observation,
)

FIXTURE = Path(__file__).parent / "fixtures" / "normalization_contracts.json"


def rows():
    """Load only invented values used by this contract test."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def reference(source: str, row: int = 2) -> SourceReference:
    return SourceReference(source_name=source, row_reference=f"row-{row}")


def test_validates_each_source_shape_and_preserves_optional_values():
    fixture = rows()

    current = validate_current_record(fixture["current"], reference("current"))
    snapshot = validate_snapshot_observation(fixture["snapshot"], reference("history"))
    change = validate_membership_change(fixture["change"], reference("changes"))
    activity = validate_activity_record(fixture["activity"], reference("activity"))

    assert isinstance(current, CurrentRecord)
    assert current.imis_id == "SYN-100"
    assert current.status == "A"
    assert isinstance(snapshot, SnapshotObservation)
    assert snapshot.status == "I"
    assert isinstance(change, MembershipChange)
    assert change.change_effective is None
    assert isinstance(activity, ActivityRecord)
    assert activity.transaction_date is None


def test_required_blank_values_return_detailed_rejection_without_losing_evidence():
    rejected = validate_current_record(
        rows()["missing_current"], reference("current", 7)
    )

    assert rejected.reference == reference("current", 7)
    assert [failure.field for failure in rejected.failures] == [
        "iMIS Id",
        "Member Type",
        "Last Updated",
    ]
    assert rejected.raw_fields[0].value == "   "
    assert rejected.raw_fields[-1].value == ""


@pytest.mark.parametrize(
    ("fixture_name", "validator", "required_field"),
    [
        ("current", validate_current_record, "iMIS Id"),
        ("snapshot", validate_snapshot_observation, "Member Type"),
        ("change", validate_membership_change, "ChangeID"),
        ("activity", validate_activity_record, "A_Transaction"),
    ],
)
def test_each_shape_rejects_missing_and_blank_required_fields(
    fixture_name, validator, required_field
):
    blank_row = rows()[fixture_name]
    blank_row[required_field] = "  "
    missing_row = dict(rows()[fixture_name])
    del missing_row[required_field]

    blank_rejection = validator(blank_row, reference(fixture_name))
    missing_rejection = validator(missing_row, reference(fixture_name, 3))

    assert blank_rejection.failures[0].field == required_field
    assert missing_rejection.failures[0].field == required_field


def test_raw_fields_and_source_reference_are_verbatim_and_records_are_immutable():
    row = rows()["current"]
    row["Company"] = "  Example Steel  "

    record = validate_current_record(row, reference("CSContactBasic_current.csv", 42))

    assert record.reference.row_reference == "row-42"
    assert record.raw_value("Company") == "  Example Steel  "
    assert record.raw_value("Not present") is None
    assert record.raw_fields[-1].name == "Company"


def test_batch_keeps_duplicates_conflicts_and_input_order_without_reconciliation():
    fixture = rows()
    result = validate_current_records(
        (reference("current", number), row)
        for number, row in enumerate(fixture["preserved_rows"], start=2)
    )

    assert [record.last_updated for record in result.accepted] == [
        "2026-10-03",
        "2026-10-03",
        "2026-01-01",
    ]
    assert [record.status for record in result.accepted] == ["A", "I", "A"]
    assert result.rejected == ()


def test_batch_returns_accepted_and_rejected_rows_together():
    fixture = rows()
    result = validate_current_records(
        [
            (reference("current", 2), fixture["current"]),
            (reference("current", 7), fixture["missing_current"]),
        ]
    )

    assert len(result.accepted) == 1
    assert len(result.rejected) == 1
    assert result.rejected[0].reference.row_reference == "row-7"
    assert result.rejected[0].raw_value("iMIS Id") == "   "
    assert result.rejected[0].failures[0].code == "required"
