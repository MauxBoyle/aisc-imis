"""Tests for normalized observations converted to immutable ledger records."""

from datetime import date

import pytest

from aisc_imis.activity_history_records import read_activity_history_records
from aisc_imis.current_member_records import read_current_member_records
from aisc_imis.evidence_conversion import (
    convert_activity_history_observations,
    convert_current_member_observations,
    convert_historical_snapshot_observations,
    convert_membership_change_observations,
)
from aisc_imis.evidence_ledger import (
    CandidateLifecycleEvent,
    InterpretationStatus,
    ObservedFact,
)
from aisc_imis.historical_snapshot_records import read_historical_snapshot_records
from aisc_imis.membership_change_records import read_membership_change_records


@pytest.fixture
def references(tmp_path):
    directory = tmp_path / "references"
    directory.mkdir()
    (directory / "member_types.csv").write_text("code\nACT\n", encoding="utf-8")
    (directory / "statuses.csv").write_text("code\nA\n", encoding="utf-8")
    (directory / "snapshot_dates.csv").write_text(
        "snapshot_date\n2026-01-03\n", encoding="utf-8"
    )
    (directory / "lifecycle-evidence-taxonomy.csv").write_text(
        "source,field,code,evidence_class,assertion_level,draft_lifecycle_name,"
        "countability_effect\n"
        "Membership changes,Change Type,JOIN,lifecycle candidate,possible inference,joined,increases\n"
        "Membership changes,Change Type,UNKNOWN,unknown,possible inference,unknown,unresolved\n"
        "Activity history,Activity Type,LEAVE,lifecycle candidate,possible inference,resigned,decreases\n"
        "Activity history,Activity Type,DUES,payment activity,direct fact,,unresolved\n"
        "Activity history,Activity Type,UNKNOWN,unknown,possible inference,unknown,unresolved\n",
        encoding="utf-8",
    )
    return directory


def test_current_and_historical_rows_emit_ordered_state_observations(tmp_path, references):
    source = tmp_path / "current.csv"
    source.write_text(
        "iMIS Id,Member Type,Is Company,Is Member,Last Updated,Status\n"
        "00017,ACT,False,True,2026-01-02,A\n",
        encoding="utf-8",
    )
    current_result = convert_current_member_observations(
        read_current_member_records(source, references).observations
    )
    historical_result = convert_historical_snapshot_observations(
        read_historical_snapshot_records(source, references).observations
    )

    assert [record.state_name for record in current_result.records] == [
        "member_type=ACT", "status=A", "is_member=True", "is_company=False"
    ]
    assert all(record.subject_key == "00017" for record in current_result.records)
    assert all(record.recorded_date == date(2026, 1, 2) for record in current_result.records)
    assert all(record.observed_date is None for record in current_result.records)
    assert all(record.observed_date == date(2026, 1, 3) for record in historical_result.records)
    assert all(record.source_reference.row_reference == "row-2" for record in historical_result.records)


def test_snapshot_join_date_is_a_fact_available_on_export_date(tmp_path, references):
    source = tmp_path / "current.csv"
    source.write_text(
        "iMIS Id,Member Type,Is Company,Is Member,Last Updated,Join Date\n"
        "00017,ACT,True,True,2026-09-20,2026-09-16\n",
        encoding="utf-8",
    )
    result = convert_current_member_observations(
        read_current_member_records(source, references).observations,
        export_date=date(2026, 10, 15),
    )
    join = next(record for record in result.records if isinstance(record, ObservedFact))
    assert (join.fact_name, join.fact_value) == ("join_date", "2026-09-16")
    assert (join.recorded_date, join.observed_date) == (date(2026, 10, 15), date(2026, 10, 15))


def test_membership_change_is_unlinked_and_cannot_move_a_company(tmp_path, references):
    source = tmp_path / "changes.csv"
    source.write_text(
        "ChangeID,Ordinal,Change Type,Member Type,ChangeUpdate,ChangeCreated,Status,ChangeEffective\n"
        "00017,1,JOIN,ACT,2026-01-04,2026-01-03,A,2026-01-02\n",
        encoding="utf-8",
    )
    result = convert_membership_change_observations(
        read_membership_change_records(source, references).observations
    )
    record = result.records[0]

    assert isinstance(record, ObservedFact)
    assert (record.subject_key, record.fact_name, record.fact_value) == ("00017", "unlinked_membership_change", "joined")
    assert (record.effective_date, record.recorded_date) == (date(2026, 1, 2), date(2026, 1, 3))
    assert record.source_reference.row_reference == "row-2"
    assert [finding.code for finding in result.findings] == ["unlinked_membership_change"]


def test_unresolved_membership_change_is_a_fact_with_a_finding(tmp_path, references):
    source = tmp_path / "changes.csv"
    source.write_text(
        "ChangeID,Ordinal,Change Type,Member Type,ChangeUpdate,ChangeCreated,Status\n"
        "C-1,1,UNKNOWN,ACT,2026-01-04,2026-01-03,A\n",
        encoding="utf-8",
    )
    result = convert_membership_change_observations(
        read_membership_change_records(source, references).observations
    )

    assert isinstance(result.records[0], ObservedFact)
    assert result.records[0].interpretation_status == InterpretationStatus.UNRESOLVED
    assert [finding.code for finding in result.findings] == ["unresolved_change_type_conversion"]


def test_conflicting_activity_mapping_is_retained_as_unresolved_evidence(tmp_path, references):
    taxonomy = references / "lifecycle-evidence-taxonomy.csv"
    taxonomy.write_text(
        taxonomy.read_text(encoding="utf-8")
        + "Activity history,Activity Type,CONFLICT,lifecycle candidate,possible inference,resigned,decreases\n"
        + "Activity history,Activity Type,CONFLICT,lifecycle candidate,possible inference,reinstated,increases\n",
        encoding="utf-8",
    )
    source = tmp_path / "activity.csv"
    source.write_text(
        "iMIS Id,Sequence,A_Transaction,Activity Type,Effective Date,Member Type,Is a Company\n"
        "00017,1,TX-1,CONFLICT,2026-01-02,ACT,False\n",
        encoding="utf-8",
    )

    result = convert_activity_history_observations(
        read_activity_history_records(source, references).observations
    )

    assert isinstance(result.records[0], ObservedFact)
    assert result.records[0].interpretation_status == InterpretationStatus.UNRESOLVED
    assert [finding.code for finding in result.findings] == [
        "unresolved_activity_type_conversion"
    ]


@pytest.mark.parametrize(
    ("activity_type", "record_type", "name", "finding"),
    [
        ("LEAVE", CandidateLifecycleEvent, "resigned", None),
        ("DUES", ObservedFact, "payment_activity", None),
        ("UNKNOWN", ObservedFact, "activity_type", "unresolved_activity_type_conversion"),
        ("UNMAPPED", ObservedFact, "activity_type", "unresolved_activity_type_conversion"),
    ],
)
def test_activity_conversion_keeps_dates_provenance_and_unresolved_codes_nontransitions(
    tmp_path, references, activity_type, record_type, name, finding
):
    source = tmp_path / "activity.csv"
    source.write_text(
        "iMIS Id,Sequence,A_Transaction,Activity Type,Effective Date,Member Type,Is a Company,Transaction Date\n"
        f"00017,1,TX-1,{activity_type},2026-01-02,ACT,False,2026-01-03\n",
        encoding="utf-8",
    )
    result = convert_activity_history_observations(
        read_activity_history_records(source, references).observations
    )
    record = result.records[0]

    assert isinstance(record, record_type)
    assert (record.effective_date, record.recorded_date) == (date(2026, 1, 2), date(2026, 1, 3))
    if isinstance(record, CandidateLifecycleEvent):
        assert record.event_name == name
        assert record.source_references[0].row_reference == "row-2"
    else:
        assert record.fact_name == name
        assert record.source_reference.row_reference == "row-2"
    assert [item.code for item in result.findings] == ([] if finding is None else [finding])


def test_activity_uses_transaction_date_when_effective_date_is_missing(tmp_path, references):
    source = tmp_path / "activity.csv"
    source.write_text(
        "iMIS Id,Sequence,A_Transaction,Activity Type,Effective Date,Member Type,Is a Company,Transaction Date\n"
        "00017,1,TX-1,LEAVE,,ACT,True,2026-03-01\n",
        encoding="utf-8",
    )
    result = convert_activity_history_observations(
        read_activity_history_records(source, references).observations
    )
    record = result.records[0]
    assert isinstance(record, CandidateLifecycleEvent)
    assert record.effective_date == date(2026, 3, 1)
    assert record.recorded_date == date(2026, 3, 1)
    assert record.date_basis == "transaction_date"
