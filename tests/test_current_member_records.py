"""Tests for the local current-member CSV adapter using invented data only."""

from datetime import date

import pytest

from aisc_imis.current_member_records import read_current_member_records

HEADERS = "iMIS Id,Member Type,Is Company,Is Member,Last Updated,Status\n"


@pytest.fixture(autouse=True)
def reviewed_reference_tables(tmp_path):
    """Create small invented reviewed codebooks for each test."""
    reference_dir = tmp_path / "references"
    reference_dir.mkdir()
    (reference_dir / "member_types.csv").write_text(
        "code,meaning\nACT,Active member\n", encoding="utf-8"
    )
    (reference_dir / "statuses.csv").write_text(
        "code,meaning\nA,Active\n", encoding="utf-8"
    )


def write_csv(tmp_path, content: str, name: str = "current.csv"):
    """Write an invented local CSV and return its path."""
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_reads_valid_rows_as_immutable_present_state_observations(tmp_path):
    source = write_csv(
        tmp_path,
        HEADERS + "000139,ACT,True,False,10/15/2026,A\n",
    )

    result = read_current_member_records(source, tmp_path / "references")
    observation = result.observations[0]

    assert observation.record.reference.source_name == "current.csv"
    assert observation.record.reference.row_reference == "row-2"
    assert observation.record.raw_value("iMIS Id") == "000139"
    assert observation.imis_id == "000139"
    assert observation.member_type == "ACT"
    assert observation.is_company is True
    assert observation.is_member is False
    assert observation.last_updated == date(2026, 10, 15)
    assert observation.status == "A"
    assert result.rejections == ()
    assert result.findings == ()
    with pytest.raises(AttributeError):
        observation.imis_id = "changed"


def test_handles_utf8_bom_and_preserves_identifier_leading_zeroes(tmp_path):
    source = write_csv(tmp_path, HEADERS + "000001,ACT,False,True,2026-10-15,\n")
    source.write_text("\ufeff" + source.read_text(encoding="utf-8"), encoding="utf-8")

    result = read_current_member_records(source, tmp_path / "references")

    assert result.observations[0].imis_id == "000001"
    assert result.observations[0].status is None
    assert result.findings == ()


def test_missing_required_headers_returns_batch_finding_without_rows(tmp_path):
    source = write_csv(tmp_path, "iMIS Id,Member Type,Is Company\nSYN-1,ACT,True\n")

    result = read_current_member_records(source, tmp_path / "references")

    assert result.observations == ()
    assert result.rejections == ()
    assert [(finding.code, finding.field) for finding in result.findings] == [
        ("missing_required_header", "Is Member"),
        ("missing_required_header", "Last Updated"),
    ]


def test_missing_required_values_are_rejected_with_raw_evidence(tmp_path):
    source = write_csv(tmp_path, HEADERS + " ,ACT,True,False,,A\n")

    result = read_current_member_records(source, tmp_path / "references")

    assert result.observations == ()
    assert len(result.rejections) == 1
    assert result.rejections[0].reference.row_reference == "row-2"
    assert result.rejections[0].raw_value("iMIS Id") == " "
    assert [failure.field for failure in result.rejections[0].failures] == [
        "iMIS Id",
        "Last Updated",
    ]


def test_invalid_flags_and_dates_keep_observation_and_report_findings(tmp_path):
    source = write_csv(tmp_path, HEADERS + "SYN-1,ACT,yes,nope,not-a-date,A\n")

    result = read_current_member_records(source, tmp_path / "references")
    observation = result.observations[0]

    assert observation.is_company is None
    assert observation.is_member is None
    assert observation.last_updated is None
    assert [(finding.field, finding.code) for finding in result.findings] == [
        ("Is Company", "invalid"),
        ("Is Member", "invalid"),
        ("Last Updated", "invalid"),
    ]


def test_unknown_member_type_and_status_keep_observation_and_report_findings(tmp_path):
    source = write_csv(tmp_path, HEADERS + "SYN-1,NEW,True,True,2026-10-15,ZZ\n")

    result = read_current_member_records(source, tmp_path / "references")
    observation = result.observations[0]

    assert observation.member_type is None
    assert observation.status is None
    assert [(finding.field, finding.code) for finding in result.findings] == [
        ("Member Type", "invalid"),
        ("Status", "invalid"),
    ]


def test_reports_every_duplicate_normalized_identifier_without_dropping_rows(tmp_path):
    source = write_csv(
        tmp_path,
        HEADERS
        + " 000139 ,ACT,True,True,2026-10-15,A\n"
        + "000139,ACT,False,True,2026-10-16,A\n",
    )

    result = read_current_member_records(source, tmp_path / "references")

    assert [observation.imis_id for observation in result.observations] == [
        "000139",
        "000139",
    ]
    duplicates = [finding for finding in result.findings if finding.code == "duplicate_imis_id"]
    assert [finding.reference.row_reference for finding in duplicates] == ["row-2", "row-3"]
