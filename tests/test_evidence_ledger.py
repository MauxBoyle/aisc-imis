"""Tests for the provenance-rich, UI-independent evidence ledger."""

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime

import pytest

from aisc_imis.evidence_ledger import (
    CandidateLifecycleEvent,
    InterpretationStatus,
    ObservedFact,
    SnapshotStateObservation,
    from_tabular_rows,
    to_tabular_rows,
)
from aisc_imis.normalization_contracts import SourceReference


def source(name: str, row: str) -> SourceReference:
    return SourceReference(source_name=name, row_reference=row)


def test_records_are_immutable_and_keep_date_meanings_separate():
    recorded = datetime(2026, 4, 2, 9, 15, tzinfo=UTC)
    fact = ObservedFact(
        subject_key="subject-elm",
        fact_name="membership_status",
        fact_value="active",
        source_reference=source("invented-current.csv", "row-7"),
        effective_date=date(2026, 4, 1),
        recorded_date=recorded,
        observed_date=date(2026, 4, 3),
    )

    assert fact.effective_date == date(2026, 4, 1)
    assert fact.recorded_date == recorded
    assert fact.observed_date == date(2026, 4, 3)
    with pytest.raises(FrozenInstanceError):
        fact.fact_value = "inactive"  # type: ignore[misc]


def test_all_record_types_round_trip_through_one_table_without_losing_types():
    records = (
        ObservedFact(
            subject_key="subject-elm",
            fact_name="member_type",
            fact_value="invented-type",
            source_reference=source("invented-current.csv", "row-4"),
            recorded_date=datetime(2026, 5, 1, 10, 30, 45),
            interpretation_status=InterpretationStatus.VERIFIED,
        ),
        CandidateLifecycleEvent(
            subject_key="subject-elm",
            event_name="possible_joining",
            source_references=(
                source("invented-changes.csv", "row-9"),
                source("invented-activity.csv", "row-2"),
            ),
            interpretation_reason="The two source rows describe the same possible change.",
            effective_date=date(2026, 5, 2),
            observed_date=datetime(2026, 5, 3, 12, 0, tzinfo=UTC),
            interpretation_status=InterpretationStatus.INFERRED,
        ),
        SnapshotStateObservation(
            subject_key="subject-elm",
            state_name="active",
            source_reference=source("invented-history.csv", "row-12"),
            observed_date=date(2026, 5, 4),
            interpretation_status=InterpretationStatus.AMBIGUOUS,
        ),
    )

    rows = to_tabular_rows(records)

    assert [row["record_type"] for row in rows] == [
        "observed_fact",
        "candidate_lifecycle_event",
        "snapshot_state_observation",
    ]
    assert rows[1]["source_references"] == (
        '[{"source_name":"invented-changes.csv","row_reference":"row-9"},'
        '{"source_name":"invented-activity.csv","row_reference":"row-2"}]'
    )
    assert from_tabular_rows(rows) == records


@pytest.mark.parametrize(
    ("sources", "reason"),
    [
        ((), "A reason."),
        ((source("invented.csv", "row-1"),), "  "),
    ],
)
def test_candidate_event_requires_sources_and_nonblank_reason(sources, reason):
    with pytest.raises(ValueError):
        CandidateLifecycleEvent(
            subject_key="subject-elm",
            event_name="possible_change",
            source_references=sources,
            interpretation_reason=reason,
        )


def test_interpretation_statuses_remain_distinct():
    records = tuple(
        ObservedFact(
            subject_key=f"subject-{status.value}",
            fact_name="status",
            fact_value="invented",
            source_reference=source("invented.csv", f"row-{index}"),
            interpretation_status=status,
        )
        for index, status in enumerate(InterpretationStatus, start=1)
    )

    restored = from_tabular_rows(to_tabular_rows(records))

    assert [record.interpretation_status for record in restored] == list(
        InterpretationStatus
    )


def test_contradictory_records_for_one_subject_coexist_unchanged():
    active = ObservedFact(
        subject_key="subject-elm",
        fact_name="membership_status",
        fact_value="active",
        source_reference=source("invented-a.csv", "row-1"),
    )
    inactive = ObservedFact(
        subject_key="subject-elm",
        fact_name="membership_status",
        fact_value="inactive",
        source_reference=source("invented-b.csv", "row-8"),
    )

    assert from_tabular_rows(to_tabular_rows((active, inactive))) == (active, inactive)


@pytest.mark.parametrize(
    "row",
    [
        {"record_type": "not_a_record"},
        {"record_type": "observed_fact", "interpretation_status": "maybe"},
        {
            "record_type": "observed_fact",
            "interpretation_status": "verified",
            "effective_date": "not-a-date",
        },
    ],
)
def test_malformed_table_rows_are_rejected(row):
    with pytest.raises(ValueError):
        from_tabular_rows((row,))
