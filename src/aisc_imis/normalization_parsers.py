"""Small, lossless parsing helpers for future source adapters.

The functions in this module know only how to parse individual values.  They
do not read files, assign business meaning, or decide how a source column maps
to a record field.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, TypeVar

ParsedValue = date | datetime
NumericDateFormat = Literal["mdy", "dmy"]
T = TypeVar("T")


@dataclass(frozen=True)
class ParseFinding:
    """One structured reason a value could not be normalized."""

    code: Literal["blank", "invalid", "ambiguous"]
    message: str


@dataclass(frozen=True)
class ParseResult[T]:
    """The unmodified input, its parsed value when available, and findings."""

    raw: str | None
    normalized: T | None
    findings: tuple[ParseFinding, ...] = ()


def parse_identifier(raw: str | None) -> ParseResult[str]:
    """Trim an identifier without converting it to a number.

    Keeping identifiers as text preserves meaningful leading zeroes.
    """
    value = _trimmed_or_none(raw)
    if value is None:
        return _blank_result(raw, "Identifier is blank.")
    return ParseResult(raw=raw, normalized=value)


def parse_boolean(raw: str | None) -> ParseResult[bool]:
    """Parse the reviewed iMIS ``True`` and ``False`` text values."""
    value = _trimmed_or_none(raw)
    if value is None:
        return _blank_result(raw, "Boolean value is blank.")
    if value == "True":
        return ParseResult(raw=raw, normalized=True)
    if value == "False":
        return ParseResult(raw=raw, normalized=False)
    return _invalid_result(raw, f"Unknown boolean value: {value!r}.")


def parse_member_type(
    raw: str | None, codebook: Mapping[str, object]
) -> ParseResult[str]:
    """Validate a member-type code against a caller-supplied reviewed codebook."""
    return parse_code(raw, codebook, code_kind="member type")


def parse_status(raw: str | None, codebook: Mapping[str, object]) -> ParseResult[str]:
    """Validate a status code against a caller-supplied reviewed codebook."""
    return parse_code(raw, codebook, code_kind="status")


def parse_code(
    raw: str | None, codebook: Mapping[str, object], *, code_kind: str = "code"
) -> ParseResult[str]:
    """Validate a trimmed code without interpreting the codebook's values."""
    value = _trimmed_or_none(raw)
    if value is None:
        return _blank_result(raw, f"{code_kind.capitalize()} is blank.")
    if value not in codebook:
        return _invalid_result(raw, f"Unknown {code_kind} code: {value!r}.")
    return ParseResult(raw=raw, normalized=value)


def parse_date(
    raw: str | None,
    *,
    numeric_date_formats: tuple[NumericDateFormat, ...] = ("mdy",),
) -> ParseResult[ParsedValue]:
    """Parse an ISO or known iMIS date/timestamp value.

    Numeric slash dates use month/day/year by default.  A caller may enable
    both month/day/year and day/month/year; if both produce different valid
    values, the result is deliberately ambiguous rather than guessed.
    """
    value = _trimmed_or_none(raw)
    if value is None:
        return _blank_result(raw, "Date value is blank.")

    iso_value = _parse_iso(value)
    if iso_value is not None:
        return ParseResult(raw=raw, normalized=iso_value)

    parsed_values = _parse_numeric_date(value, numeric_date_formats)
    if not parsed_values:
        return _invalid_result(raw, f"Unrecognized date or timestamp: {value!r}.")
    if len(parsed_values) > 1:
        return ParseResult(
            raw=raw,
            normalized=None,
            findings=(
                ParseFinding(
                    code="ambiguous",
                    message=(
                        "Date matches more than one enabled numeric date format: "
                        f"{value!r}."
                    ),
                ),
            ),
        )
    return ParseResult(raw=raw, normalized=parsed_values[0])


def _trimmed_or_none(raw: str | None) -> str | None:
    return raw.strip() if raw is not None and raw.strip() else None


def _blank_result(raw: str | None, message: str) -> ParseResult[object]:
    return ParseResult(
        raw=raw,
        normalized=None,
        findings=(ParseFinding(code="blank", message=message),),
    )


def _invalid_result(raw: str | None, message: str) -> ParseResult[object]:
    return ParseResult(
        raw=raw,
        normalized=None,
        findings=(ParseFinding(code="invalid", message=message),),
    )


def _parse_iso(value: str) -> ParsedValue | None:
    try:
        if "T" not in value and " " not in value:
            return date.fromisoformat(value)
        return datetime.fromisoformat(
            f"{value[:-1]}+00:00" if value.endswith("Z") else value
        )
    except ValueError:
        return None


def _parse_numeric_date(
    value: str, numeric_date_formats: tuple[NumericDateFormat, ...]
) -> tuple[ParsedValue, ...]:
    formats = {
        "mdy": ("%m/%d/%Y", "%m/%d/%Y %I:%M %p", "%m/%d/%Y %I:%M:%S %p"),
        "dmy": ("%d/%m/%Y", "%d/%m/%Y %I:%M %p", "%d/%m/%Y %I:%M:%S %p"),
    }
    unknown_formats = set(numeric_date_formats) - formats.keys()
    if unknown_formats:
        raise ValueError(f"Unknown numeric date format(s): {sorted(unknown_formats)}")

    parsed_values: list[ParsedValue] = []
    for date_format_name in numeric_date_formats:
        for date_format in formats[date_format_name]:
            try:
                parsed = datetime.strptime(value, date_format)
            except ValueError:
                continue
            normalized: ParsedValue = (
                parsed.date() if date_format == formats[date_format_name][0] else parsed
            )
            if normalized not in parsed_values:
                parsed_values.append(normalized)
    return tuple(parsed_values)
