"""Build reusable reference tables from iMIS company exports."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

BOOLEAN_VALUES = [
    {"value": "False", "meaning": "No"},
    {"value": "True", "meaning": "Yes"},
]

FIELD_DETAILS = {
    "Is Company": ("boolean", "boolean_values.csv", "Whether the record is a company."),
    "Member Type": ("code", "member_types.csv", "Current member type code."),
    "Previous Member Type": (
        "code",
        "member_types.csv",
        "Previous member type code; blank means no recorded previous type.",
    ),
    "iMIS Id": ("text", "", "iMIS record identifier."),
    "Company": ("text", "", "Company name."),
    "Full Address": ("text", "", "Full mailing address."),
    "Is Member": ("boolean", "boolean_values.csv", "Whether the record is a member."),
    "Major Key": ("text", "", "iMIS major key."),
    "Status": ("code", "statuses.csv", "Status code."),
}

TABLE_FIELDNAMES = {
    "variable_dictionary.csv": [
        "source_column",
        "data_type",
        "reference_table",
        "description",
    ],
    "boolean_values.csv": ["value", "meaning"],
    "member_types.csv": ["code", "meaning"],
    "statuses.csv": ["code", "meaning"],
}


def build_reference_tables(input_path: Path) -> dict[str, list[dict[str, str]]]:
    """Return reference-table rows derived from an iMIS CSV export."""
    with input_path.open(encoding="utf-8-sig", newline="") as export_file:
        reader = csv.DictReader(export_file)
        if not reader.fieldnames:
            raise ValueError("The iMIS export must include a header row.")
        rows = list(reader)

    variable_dictionary = []
    for field in reader.fieldnames:
        data_type, reference_table, description = FIELD_DETAILS.get(
            field, ("text", "", "TBD")
        )
        variable_dictionary.append(
            {
                "source_column": field,
                "data_type": data_type,
                "reference_table": reference_table,
                "description": description,
            }
        )

    member_types = _unique_codes(
        rows, ("Member Type", "Previous Member Type")
    )
    statuses = _unique_codes(rows, ("Status",))

    return {
        "variable_dictionary.csv": variable_dictionary,
        "boolean_values.csv": BOOLEAN_VALUES,
        "member_types.csv": [{"code": code, "meaning": "TBD"} for code in member_types],
        "statuses.csv": [{"code": code, "meaning": "TBD"} for code in statuses],
    }


def write_reference_tables(input_path: Path, output_dir: Path) -> list[Path]:
    """Write reference tables, retaining existing curated code meanings."""
    output_dir.mkdir(parents=True, exist_ok=True)
    tables = build_reference_tables(input_path)
    written_paths = []

    for filename, rows in tables.items():
        output_path = output_dir / filename
        if filename in {"member_types.csv", "statuses.csv"}:
            _apply_existing_meanings(rows, output_path)
        _write_csv(output_path, TABLE_FIELDNAMES[filename], rows)
        written_paths.append(output_path)

    return written_paths


def _unique_codes(
    rows: Iterable[dict[str, str | None]], fields: Iterable[str]
) -> list[str]:
    return sorted(
        {
            value.strip()
            for row in rows
            for field in fields
            if (value := row.get(field)) and value.strip()
        }
    )


def _apply_existing_meanings(rows: list[dict[str, str]], output_path: Path) -> None:
    if not output_path.exists():
        return

    with output_path.open(encoding="utf-8", newline="") as reference_file:
        existing_meanings = {
            row["code"]: row["meaning"]
            for row in csv.DictReader(reference_file)
            if row.get("code") and row.get("meaning")
        }
    for row in rows:
        row["meaning"] = existing_meanings.get(row["code"], row["meaning"])


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as reference_file:
        writer = csv.DictWriter(reference_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
