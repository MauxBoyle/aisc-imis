"""Tests for member-focused, deterministic evidence ledger views."""

from datetime import UTC, date, datetime

from aisc_imis.evidence_ledger import ObservedFact, SnapshotStateObservation
from aisc_imis.member_ledger import (
    CSV_COLUMNS,
    build_member_evidence_ledger,
    write_member_evidence_csv,
)
from aisc_imis.normalization_contracts import SourceReference


def fact(
    member: str,
    value: str,
    row: str,
    *,
    effective_date: date | datetime | None = None,
    recorded_date: date | datetime | None = None,
    observed_date: date | datetime | None = None,
) -> ObservedFact:
    return ObservedFact(
        subject_key=member,
        fact_name="membership_status",
        fact_value=value,
        source_reference=SourceReference("invented.csv", row),
        effective_date=effective_date,
        recorded_date=recorded_date,
        observed_date=observed_date,
    )


def test_groups_and_queries_only_the_requested_confirmed_member():
    elm = fact("member-elm", "active", "row-1")
    ash = fact("member-ash", "inactive", "row-2")

    ledger = build_member_evidence_ledger((ash, elm))

    assert ledger.member_keys == ("member-ash", "member-elm")
    assert ledger.records_for("member-elm") == (elm,)
    assert ledger.records_for("unknown-member") == ()
    assert tuple(entry.record for entry in ledger.entries_for("member-ash")) == (ash,)


def test_builds_have_stable_ids_and_order_even_when_input_is_shuffled():
    earlier = fact("member-elm", "pending", "row-2", effective_date=date(2026, 4, 1))
    later = fact("member-elm", "active", "row-1", effective_date=date(2026, 4, 2))
    other = fact("member-ash", "inactive", "row-3", effective_date=date(2026, 4, 3))

    first = build_member_evidence_ledger((later, other, earlier))
    second = build_member_evidence_ledger((earlier, later, other))

    assert first == second
    assert [entry.record for entry in first.entries_for("member-elm")] == [
        earlier,
        later,
    ]
    assert all(len(entry.record_id) == 64 for entry in first.entries)


def test_sorts_date_roles_with_missing_values_last_and_preserves_date_precision():
    date_only = fact("member-elm", "date", "row-1", effective_date=date(2026, 4, 1))
    timestamp = fact(
        "member-elm",
        "timestamp",
        "row-2",
        effective_date=datetime(2026, 4, 1, 0, 0, tzinfo=UTC),
    )
    later_recorded = fact(
        "member-elm",
        "recorded",
        "row-3",
        effective_date=date(2026, 4, 1),
        recorded_date=date(2026, 4, 2),
    )
    missing_effective = fact("member-elm", "missing", "row-4")

    ledger = build_member_evidence_ledger(
        (missing_effective, later_recorded, timestamp, date_only)
    )

    assert [entry.record.fact_value for entry in ledger.entries_for("member-elm")] == [
        "recorded",
        "date",
        "timestamp",
        "missing",
    ]


def test_retains_exact_duplicates_and_same_time_contradictions():
    duplicate = fact("member-elm", "active", "row-1", effective_date=date(2026, 4, 1))
    contradiction = fact(
        "member-elm", "inactive", "row-2", effective_date=date(2026, 4, 1)
    )

    ledger = build_member_evidence_ledger((contradiction, duplicate, duplicate))
    entries = ledger.entries_for("member-elm")

    assert len(entries) == 3
    assert entries[0].record_id == entries[1].record_id
    assert {entry.record.fact_value for entry in entries} == {"active", "inactive"}


def test_writes_deterministic_csv_with_ids_and_duplicate_rows(tmp_path):
    duplicate = fact("member-elm", "active", "row-1", effective_date=date(2026, 4, 1))
    state = SnapshotStateObservation(
        subject_key="member-ash",
        state_name="is_member=false",
        source_reference=SourceReference("invented.csv", "row-3"),
    )
    ledger = build_member_evidence_ledger((duplicate, state, duplicate))
    output = tmp_path / "processed" / "member-evidence.csv"

    returned_path = write_member_evidence_csv(ledger, output)
    rows = output.read_text(encoding="utf-8").splitlines()

    assert returned_path == output
    assert rows[0].split(",") == list(CSV_COLUMNS)
    assert len(rows) == 4
    assert rows[1].split(",")[0] == ledger.entries[0].record_id
    assert rows[2].split(",")[0] == ledger.entries[1].record_id
    assert rows[2] == rows[3]
