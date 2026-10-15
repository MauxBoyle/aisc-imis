"""Tests for the local historical snapshot adapter using invented data only."""

from datetime import date

import pytest

from aisc_imis.historical_snapshot_records import read_historical_snapshot_records

HEADERS = "iMIS Id,Member Type,Is Company,Is Member,Last Updated,Status\n"
SNAPSHOT_DATES = (
    "snapshot_date\n"
    "2025-06-05\n"
    "2025-06-25\n"
    "2025-06-26\n"
    "2025-07-01\n"
    "2025-07-18\n"
    "2026-03-13\n"
    "2026-06-30\n"
    "2026-07-20\n"
    "2026-10-14\n"
)


@pytest.fixture(autouse=True)
def reviewed_reference_tables(tmp_path):
    """Create small invented reviewed codebooks and schedule for every test."""
    reference_dir = tmp_path / "references"
    reference_dir.mkdir()
    (reference_dir / "member_types.csv").write_text(
        "code,meaning\nACT,Active member\n", encoding="utf-8"
    )
    (reference_dir / "statuses.csv").write_text(
        "code,meaning\nA,Active\n", encoding="utf-8"
    )
    (reference_dir / "snapshot_dates.csv").write_text(SNAPSHOT_DATES, encoding="utf-8")


def write_csv(tmp_path, content: str, name: str = "historical.csv"):
    """Write an invented local CSV and return its path."""
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_reads_valid_legacy_rows_with_raw_provenance_and_coverage_date(tmp_path):
    source = write_csv(
        tmp_path, HEADERS + "000139,ACT,True,False,2025-06-06,A\n"
    )

    result = read_historical_snapshot_records(source, tmp_path / "references")
    observation = result.observations[0]

    assert observation.record.reference.source_name == "historical.csv"
    assert observation.record.reference.row_reference == "row-2"
    assert observation.record.raw_value("iMIS Id") == "000139"
    assert observation.imis_id == "000139"
    assert observation.member_type == "ACT"
    assert observation.is_company is True
    assert observation.is_member is False
    assert observation.last_updated == date(2025, 6, 6)
    assert observation.observation_date == date(2025, 6, 25)
    assert observation.observation_date_basis == "configured_snapshot_on_or_after_last_updated"
    assert observation.status == "A"
    assert result.rejections == ()
    assert result.findings == ()
    with pytest.raises(AttributeError):
        observation.imis_id = "changed"


def test_retains_repeated_rows_and_reports_each_conflicting_same_key_row(tmp_path):
    source = write_csv(
        tmp_path,
        HEADERS
        + " 000139 ,ACT,True,True,2025-06-25,A\n"
        + "000139,ACT,True,True,2025-06-25,A\n"
        + "000139,ACT,False,True,2025-06-25,A\n",
    )

    result = read_historical_snapshot_records(source, tmp_path / "references")

    assert len(result.observations) == 3
    conflicts = [
        finding
        for finding in result.findings
        if finding.code == "conflicting_snapshot_observation"
    ]
    assert [finding.reference.row_reference for finding in conflicts] == [
        "row-2",
        "row-3",
        "row-4",
    ]


def test_assigns_first_coverage_date_and_reports_rows_after_schedule(tmp_path):
    source = write_csv(
        tmp_path,
        HEADERS
        + "SYN-1,ACT,True,True,2020-01-01,A\n"
        + "SYN-2,ACT,True,True,2027-01-01,A\n",
    )

    result = read_historical_snapshot_records(source, tmp_path / "references")

    assert result.observations[0].observation_date == date(2025, 6, 5)
    assert result.observations[1].observation_date is None
    assert [
        (finding.code, finding.reference.row_reference)
        for finding in result.findings
    ] == [("missing_observation_date", "row-3")]


def test_reports_invalid_values_and_unknown_codes_without_dropping_row(tmp_path):
    source = write_csv(
        tmp_path, HEADERS + "SYN-1,NEW,yes,nope,not-a-date,ZZ\n"
    )

    result = read_historical_snapshot_records(source, tmp_path / "references")
    observation = result.observations[0]

    assert observation.member_type is None
    assert observation.is_company is None
    assert observation.is_member is None
    assert observation.last_updated is None
    assert observation.status is None
    assert observation.observation_date is None
    assert [(finding.field, finding.code) for finding in result.findings] == [
        ("Member Type", "invalid"),
        ("Is Company", "invalid"),
        ("Is Member", "invalid"),
        ("Last Updated", "invalid"),
        ("Status", "invalid"),
        ("Last Updated", "missing_observation_date"),
    ]


def test_handles_bom_rejections_missing_headers_and_incompatible_rows(tmp_path):
    source = write_csv(tmp_path, HEADERS + "000001,ACT,False,True,2025-06-05,\n")
    source.write_text("\ufeff" + source.read_text(encoding="utf-8"), encoding="utf-8")
    result = read_historical_snapshot_records(source, tmp_path / "references")
    assert result.observations[0].imis_id == "000001"

    missing = write_csv(tmp_path, "iMIS Id,Member Type,Is Company\nSYN-1,ACT,True\n")
    missing_result = read_historical_snapshot_records(missing, tmp_path / "references")
    assert [(finding.code, finding.field) for finding in missing_result.findings] == [
        ("missing_required_header", "Is Member"),
        ("missing_required_header", "Last Updated"),
    ]

    rejected = write_csv(tmp_path, HEADERS + " ,ACT,True,False,,A\n")
    rejected_result = read_historical_snapshot_records(rejected, tmp_path / "references")
    assert rejected_result.observations == ()
    assert [failure.field for failure in rejected_result.rejections[0].failures] == [
        "iMIS Id",
        "Last Updated",
    ]

    incompatible = write_csv(
        tmp_path, HEADERS + "SYN-1,ACT,True,True,2025-06-05,A,extra\n"
    )
    incompatible_result = read_historical_snapshot_records(
        incompatible, tmp_path / "references"
    )
    assert incompatible_result.observations[0].imis_id == "SYN-1"
    assert incompatible_result.observations[0].record.raw_value("__extra_csv_value_1") == "extra"
    assert [(finding.code, finding.reference.row_reference) for finding in incompatible_result.findings] == [
        ("incompatible_source_schema", "row-2"),
    ]
