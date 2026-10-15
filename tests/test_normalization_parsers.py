"""Tests for reusable, source-interface-independent normalization parsers."""

from datetime import UTC, date, datetime

import pytest

from aisc_imis.normalization_parsers import (
    parse_boolean,
    parse_date,
    parse_identifier,
    parse_member_type,
    parse_status,
)


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("000139", "000139"),
        ("  000139  ", "000139"),
        ("SYN-100", "SYN-100"),
    ],
)
def test_identifier_parser_preserves_leading_zeroes_and_retains_raw_value(
    raw, normalized
):
    result = parse_identifier(raw)

    assert result.raw == raw
    assert result.normalized == normalized
    assert result.findings == ()


@pytest.mark.parametrize("raw", [None, "", "  "])
def test_identifier_parser_reports_blank_values(raw):
    result = parse_identifier(raw)

    assert result.raw == raw
    assert result.normalized is None
    assert [finding.code for finding in result.findings] == ["blank"]


@pytest.mark.parametrize(("raw", "normalized"), [("True", True), ("False", False)])
def test_boolean_parser_returns_python_booleans(raw, normalized):
    result = parse_boolean(raw)

    assert result.raw == raw
    assert result.normalized is normalized
    assert result.findings == ()


@pytest.mark.parametrize(
    ("raw", "finding_code"), [(None, "blank"), ("  ", "blank"), ("yes", "invalid")]
)
def test_boolean_parser_reports_blank_and_unknown_values(raw, finding_code):
    result = parse_boolean(raw)

    assert result.normalized is None
    assert [finding.code for finding in result.findings] == [finding_code]


@pytest.mark.parametrize(
    ("parser", "raw", "codebook", "normalized"),
    [
        (parse_member_type, " ACT ", {"ACT": "reviewed"}, "ACT"),
        (parse_status, " NB ", {"A": "active", "NB": "no bill"}, "NB"),
    ],
)
def test_code_parsers_validate_trimmed_codes_against_caller_codebooks(
    parser, raw, codebook, normalized
):
    result = parser(raw, codebook)

    assert result.raw == raw
    assert result.normalized == normalized
    assert result.findings == ()


@pytest.mark.parametrize(
    ("parser", "raw", "finding_code"),
    [
        (parse_member_type, "", "blank"),
        (parse_status, "UNKNOWN", "invalid"),
    ],
)
def test_code_parsers_report_blank_and_unknown_values(parser, raw, finding_code):
    result = parser(raw, {"A": "reviewed"})

    assert result.normalized is None
    assert [finding.code for finding in result.findings] == [finding_code]


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("2026-10-15", date(2026, 10, 15)),
        ("10/15/2026", date(2026, 10, 15)),
        ("10/15/2026 1:05:23 PM", datetime(2026, 10, 15, 13, 5, 23)),
        (
            "2026-10-15T13:05:23+00:00",
            datetime(2026, 10, 15, 13, 5, 23, tzinfo=UTC),
        ),
    ],
)
def test_date_parser_accepts_known_formats_and_keeps_timezone(raw, normalized):
    result = parse_date(raw)

    assert result.raw == raw
    assert result.normalized == normalized
    assert result.findings == ()


@pytest.mark.parametrize(
    ("raw", "finding_code"),
    [(None, "blank"), ("  ", "blank"), ("not a date", "invalid")],
)
def test_date_parser_reports_blank_and_invalid_values(raw, finding_code):
    result = parse_date(raw)

    assert result.normalized is None
    assert [finding.code for finding in result.findings] == [finding_code]


def test_date_parser_uses_month_day_year_for_numeric_slash_dates_by_default():
    result = parse_date("01/02/2026")

    assert result.normalized == date(2026, 1, 2)
    assert result.findings == ()


def test_date_parser_reports_ambiguous_when_caller_enables_conflicting_formats():
    result = parse_date("01/02/2026", numeric_date_formats=("mdy", "dmy"))

    assert result.normalized is None
    assert [finding.code for finding in result.findings] == ["ambiguous"]
