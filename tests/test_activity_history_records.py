"""Tests for the activity-history CSV adapter using invented data only."""

from datetime import date

import pytest

from aisc_imis.activity_history_records import read_activity_history_records

HEADERS = (
    "iMIS Id,Sequence,A_Transaction,Activity Type,Effective Date,Member Type,"
    "Is a Company,Transaction Date,Action,Source,Product,Notes,Other Metadata\n"
)


@pytest.fixture(autouse=True)
def reviewed_reference_tables(tmp_path):
    reference_dir = tmp_path / "references"
    reference_dir.mkdir()
    (reference_dir / "member_types.csv").write_text(
        "code,meaning\nACT,Active member\n", encoding="utf-8"
    )
    (reference_dir / "lifecycle-evidence-taxonomy.csv").write_text(
        "source,field,code,evidence_class,assertion_level,"
        "draft_lifecycle_name,countability_effect\n"
        "Activity history,Activity Type,REVIEWED,lifecycle candidate,possible inference,"
        "resigned,decreases\n"
        "Activity history,Activity Type,PAYMENT,payment activity,direct fact,"
        "unknown,unresolved\n"
        "Activity history,Activity Type,UNRESOLVED,unknown,possible inference,"
        "unknown,unresolved\n",
        encoding="utf-8",
    )


def write_csv(tmp_path, content: str, name: str = "activity.csv"):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_reads_rows_losslessly_and_exposes_reviewed_classification(tmp_path):
    source = write_csv(
        tmp_path,
        HEADERS
        + "00017,02,TX-004,REVIEWED,2026-10-14,ACT,True,2026-10-16,"
        "Renewal,Web,SKU-9,Invented note,keep this\n",
    )

    result = read_activity_history_records(source, tmp_path / "references")
    observation = result.observations[0]

    assert observation.record.reference.source_name == "activity.csv"
    assert observation.record.reference.row_reference == "row-2"
    assert observation.record.raw_value("iMIS Id") == "00017"
    assert observation.record.raw_value("Action") == "Renewal"
    assert observation.record.raw_value("Source") == "Web"
    assert observation.record.raw_value("Product") == "SKU-9"
    assert observation.record.raw_value("Notes") == "Invented note"
    assert observation.record.raw_value("Other Metadata") == "keep this"
    assert observation.imis_id == "00017"
    assert observation.sequence == "02"
    assert observation.transaction == "TX-004"
    assert observation.effective_date == date(2026, 10, 14)
    assert observation.transaction_date == date(2026, 10, 16)
    assert observation.activity_classification.evidence_class == "lifecycle candidate"
    assert observation.activity_classification.draft_lifecycle_name == "resigned"
    assert result.rejections == ()
    assert result.findings == ()
    with pytest.raises(AttributeError):
        observation.sequence = "changed"


def test_payment_classification_is_exposed_without_a_membership_transition(tmp_path):
    source = write_csv(
        tmp_path,
        HEADERS + "001,1,TX-1,PAYMENT,2026-10-14,ACT,False,,,Online,Card,DUES,paid,\n",
    )

    result = read_activity_history_records(source, tmp_path / "references")
    classification = result.observations[0].activity_classification

    assert classification.evidence_class == "payment activity"
    assert classification.draft_lifecycle_name == "unknown"
    assert classification.countability_effect == "unresolved"
    assert "unresolved_activity_type_mapping" not in {
        finding.code for finding in result.findings
    }


def test_reports_unknown_unresolved_and_conflicting_activity_type_mappings(tmp_path):
    reference_dir = tmp_path / "references"
    taxonomy = reference_dir / "lifecycle-evidence-taxonomy.csv"
    taxonomy.write_text(
        taxonomy.read_text(encoding="utf-8")
        + "Activity history,Activity Type,CONFLICT,lifecycle candidate,possible inference,"
        "resigned,decreases\n"
        + "Activity history,Activity Type,CONFLICT,lifecycle candidate,possible inference,"
        "reinstated,increases\n",
        encoding="utf-8",
    )
    source = write_csv(
        tmp_path,
        HEADERS
        + "1,1,T1,UNRESOLVED,2026-10-14,ACT,True,,,,,,\n"
        + "2,1,T2,UNKNOWN,2026-10-14,ACT,True,,,,,,\n"
        + "3,1,T3,CONFLICT,2026-10-14,ACT,True,,,,,,\n",
    )

    result = read_activity_history_records(source, reference_dir)

    assert [item.activity_classification for item in result.observations] == [
        result.observations[0].activity_classification,
        None,
        None,
    ]
    assert [(item.code, item.reference.row_reference) for item in result.findings] == [
        ("unresolved_activity_type_mapping", "row-2"),
        ("unmapped_activity_type", "row-3"),
        ("conflicting_activity_type_mapping", "row-4"),
    ]


def test_invalid_values_and_duplicate_member_sequence_are_retained_for_review(tmp_path):
    source = write_csv(
        tmp_path,
        HEADERS
        + " 00017 ,02,TX-1,REVIEWED,not-a-date,NOT-REVIEWED,yes,not-a-date,,,,,\n"
        + "00017,02,TX-2,REVIEWED,2026-10-15,ACT,False,,,,,,\n",
    )

    result = read_activity_history_records(source, tmp_path / "references")

    assert [item.imis_id for item in result.observations] == ["00017", "00017"]
    assert result.observations[0].member_type is None
    assert result.observations[0].is_company is None
    assert result.observations[0].effective_date is None
    assert result.observations[0].transaction_date is None
    assert [(item.field, item.code) for item in result.findings] == [
        ("Member Type", "invalid"),
        ("Is a Company", "invalid"),
        ("Effective Date", "invalid"),
        ("Transaction Date", "invalid"),
        ("iMIS Id", "duplicate_member_sequence"),
        ("iMIS Id", "duplicate_member_sequence"),
    ]


def test_required_values_are_rejected_but_transaction_date_is_optional(tmp_path):
    missing_headers = write_csv(tmp_path, "iMIS Id,Sequence\n00017,02\n")
    missing = read_activity_history_records(missing_headers, tmp_path / "references")
    assert [(item.code, item.field) for item in missing.findings] == [
        ("missing_required_header", "A_Transaction"),
        ("missing_required_header", "Activity Type"),
        ("missing_required_header", "Effective Date"),
        ("missing_required_header", "Member Type"),
        ("missing_required_header", "Is a Company"),
    ]

    source = write_csv(
        tmp_path, HEADERS + " , , ,REVIEWED,,ACT,True,,,,,,\n", "missing-values.csv"
    )
    rejected = read_activity_history_records(source, tmp_path / "references")
    assert [failure.field for failure in rejected.rejections[0].failures] == [
        "iMIS Id",
        "Sequence",
        "A_Transaction",
        "Effective Date",
    ]

    optional = write_csv(
        tmp_path, HEADERS + "1,1,T1,REVIEWED,2026-10-14,ACT,True,,,,,,\n"
    )
    assert (
        read_activity_history_records(optional, tmp_path / "references")
        .observations[0]
        .transaction_date
        is None
    )


def test_reports_unreadable_source(tmp_path):
    result = read_activity_history_records(tmp_path / "absent.csv", tmp_path / "references")

    assert [(item.code, item.reference) for item in result.findings] == [
        ("source_unreadable", None)
    ]
