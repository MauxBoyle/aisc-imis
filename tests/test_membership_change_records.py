"""Tests for the membership-change CSV adapter using invented data only."""

from datetime import date

import pytest

from aisc_imis.membership_change_records import read_membership_change_records

HEADERS = (
    "ChangeID,Ordinal,Change Type,Member Type,ChangeUpdate,ChangeCreated,Status,"
    "ChangeEffective,Notes,Other Date,Unreviewed Code\n"
)


@pytest.fixture(autouse=True)
def reviewed_reference_tables(tmp_path):
    reference_dir = tmp_path / "references"
    reference_dir.mkdir()
    (reference_dir / "member_types.csv").write_text(
        "code,meaning\nACT,Active member\n", encoding="utf-8"
    )
    (reference_dir / "statuses.csv").write_text(
        "code,meaning\nA,Active\n", encoding="utf-8"
    )
    (reference_dir / "lifecycle-evidence-taxonomy.csv").write_text(
        "source,field,code,draft_lifecycle_name,countability_effect\n"
        "Membership changes,Change Type,REVIEWED,resigned,decreases\n"
        "Membership changes,Change Type,UNRESOLVED,unknown,unresolved\n",
        encoding="utf-8",
    )


def write_csv(tmp_path, content: str, name: str = "changes.csv"):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_reads_reviewed_mappings_and_retains_lossless_provenance(tmp_path):
    source = write_csv(
        tmp_path,
        HEADERS + "00017,02,REVIEWED,ACT,2026-10-16,2026-10-15,A,2026-10-14,Invented note,2026-01-01,X9\n",
    )

    result = read_membership_change_records(source, tmp_path / "references")
    observation = result.observations[0]

    assert observation.record.reference.source_name == "changes.csv"
    assert observation.record.reference.row_reference == "row-2"
    assert observation.record.raw_value("ChangeID") == "00017"
    assert observation.record.raw_value("Notes") == "Invented note"
    assert observation.record.raw_value("Other Date") == "2026-01-01"
    assert observation.record.raw_value("Unreviewed Code") == "X9"
    assert observation.change_id == "00017"
    assert observation.ordinal == "02"
    assert observation.change_type == "REVIEWED"
    assert observation.member_type == "ACT"
    assert observation.status == "A"
    assert observation.change_effective == date(2026, 10, 14)
    assert observation.change_created == date(2026, 10, 15)
    assert observation.change_update == date(2026, 10, 16)
    assert result.rejections == ()
    assert result.findings == ()
    with pytest.raises(AttributeError):
        observation.change_id = "changed"


def test_unresolved_and_unknown_change_types_remain_evidence_with_findings(tmp_path):
    source = write_csv(
        tmp_path,
        HEADERS
        + "A-1,1,UNRESOLVED,ACT,2026-10-16,2026-10-15,A,,,,\n"
        + "A-2,1,UNMAPPED,ACT,2026-10-16,2026-10-15,A,,,,\n",
    )

    result = read_membership_change_records(source, tmp_path / "references")

    assert [observation.change_type for observation in result.observations] == [
        "UNRESOLVED",
        "UNMAPPED",
    ]
    assert [(finding.code, finding.reference.row_reference) for finding in result.findings] == [
        ("unresolved_change_type_mapping", "row-2"),
        ("unmapped_change_type", "row-3"),
    ]


def test_conflicting_taxonomy_and_unknown_reviewed_codes_are_findings(tmp_path):
    reference_dir = tmp_path / "references"
    (reference_dir / "lifecycle-evidence-taxonomy.csv").write_text(
        "source,field,code,draft_lifecycle_name,countability_effect\n"
        "Membership changes,Change Type,CONFLICT,resigned,decreases\n"
        "Membership changes,Change Type,CONFLICT,reinstated,increases\n",
        encoding="utf-8",
    )
    source = write_csv(
        tmp_path,
        HEADERS + "C-3,1,CONFLICT,NOT-REVIEWED,2026-10-16,2026-10-15,ZZ,,,,\n",
    )

    result = read_membership_change_records(source, reference_dir)

    assert result.observations[0].member_type is None
    assert result.observations[0].status is None
    assert [(finding.field, finding.code) for finding in result.findings] == [
        ("Member Type", "invalid"),
        ("Status", "invalid"),
        ("Change Type", "conflicting_change_type_mapping"),
    ]


def test_duplicate_transaction_keys_are_reported_without_dropping_rows(tmp_path):
    source = write_csv(
        tmp_path,
        HEADERS
        + "00017,02,REVIEWED,ACT,2026-10-16,2026-10-15,A,,,,\n"
        + "00017,02,REVIEWED,ACT,2026-10-14,2026-10-13,A,,,,\n",
    )

    result = read_membership_change_records(source, tmp_path / "references")

    assert [observation.change_update for observation in result.observations] == [
        date(2026, 10, 16),
        date(2026, 10, 14),
    ]
    duplicates = [item for item in result.findings if item.code == "duplicate_transaction_key"]
    assert [item.reference.row_reference for item in duplicates] == ["row-2", "row-3"]


def test_required_headers_and_values_are_structural_failures_but_effective_is_optional(tmp_path):
    missing_headers = write_csv(tmp_path, "ChangeID,Ordinal,Change Type\nC-1,1,REVIEWED\n")
    missing_result = read_membership_change_records(missing_headers, tmp_path / "references")

    assert [(item.code, item.field) for item in missing_result.findings] == [
        ("missing_required_header", "Member Type"),
        ("missing_required_header", "ChangeUpdate"),
        ("missing_required_header", "ChangeCreated"),
        ("missing_required_header", "Status"),
    ]

    source = write_csv(
        tmp_path,
        HEADERS + " ,1,REVIEWED,ACT,,2026-10-15,A,,,,\n",
        "missing-values.csv",
    )
    result = read_membership_change_records(source, tmp_path / "references")

    assert [failure.field for failure in result.rejections[0].failures] == [
        "ChangeID",
        "ChangeUpdate",
    ]

    optional_effective = write_csv(
        tmp_path,
        HEADERS + "C-2,1,REVIEWED,ACT,2026-10-16,2026-10-15,A,,,,\n",
        "optional-effective.csv",
    )
    optional_result = read_membership_change_records(
        optional_effective, tmp_path / "references"
    )
    assert optional_result.observations[0].change_effective is None
    assert optional_result.findings == ()


def test_dates_are_separate_invalid_dates_are_findings_and_input_order_is_preserved(tmp_path):
    source = write_csv(
        tmp_path,
        HEADERS
        + "C-2,1,REVIEWED,ACT,not-a-date,2026-12-02,A,2026-12-03,,,\n"
        + "C-1,1,REVIEWED,ACT,2026-01-01,not-a-date,A,not-a-date,,,\n",
    )

    result = read_membership_change_records(source, tmp_path / "references")

    assert [observation.change_id for observation in result.observations] == ["C-2", "C-1"]
    assert result.observations[0].change_created == date(2026, 12, 2)
    assert result.observations[0].change_effective == date(2026, 12, 3)
    assert result.observations[0].change_update is None
    assert result.observations[1].change_update == date(2026, 1, 1)
    assert result.observations[1].change_created is None
    assert result.observations[1].change_effective is None
    assert [(item.field, item.code) for item in result.findings] == [
        ("ChangeUpdate", "invalid"),
        ("ChangeCreated", "invalid"),
        ("ChangeEffective", "invalid"),
    ]
