"""Write one review row for each unresolved CSContactBasic conflict group."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

DEFAULT_INPUT = Path("data/processed/CSContactBasic_combined_deduplicated.csv")
DEFAULT_OUTPUT = Path("data/processed/CSContactBasic_remaining_conflicts.csv")
KEY_COLUMNS = ("iMIS Id", "Last Updated")
REPORT_COLUMNS = (
    "Date",
    "iMIS ID",
    "Name",
    "Company",
    "Is Company",
    "Member Type",
    "Company Member Type",
    "Is Member",
    "Status",
    "Member Status",
    "Conflict Fields",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rows_written = write_conflict_report(args.input, args.output)
    print(f"Conflict groups: {rows_written:,}")
    print(f"Output: {args.output}")


def write_conflict_report(input_path: Path, output_path: Path) -> int:
    """Write one row per unresolved conflict, combining distinct values with ``|``."""
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    with input_path.open(encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        fieldnames = reader.fieldnames or []
        for row in reader:
            groups[(row["iMIS Id"], row["Last Updated"])].append(row)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows_written = 0
    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        for (imis_id, updated), rows in sorted(groups.items()):
            conflict_fields = _conflict_fields(rows, fieldnames)
            if not conflict_fields:
                continue
            writer.writerow(
                {
                    "Date": updated,
                    "iMIS ID": imis_id,
                    "Name": _values(rows, "Full Name"),
                    "Company": _values(rows, "Company"),
                    "Is Company": _values(rows, "Is Company"),
                    "Member Type": _values(rows, "Member Type"),
                    "Company Member Type": _values(rows, "Company Member Type"),
                    "Is Member": _values(rows, "Is Member"),
                    "Status": _values(rows, "Status"),
                    "Member Status": _values(rows, "Member Status"),
                    "Conflict Fields": " | ".join(conflict_fields),
                }
            )
            rows_written += 1
    return rows_written


def _conflict_fields(rows: list[dict[str, str]], fields: list[str]) -> list[str]:
    return [
        field
        for field in fields
        if field not in KEY_COLUMNS and len(_distinct_values(rows, field)) > 1
    ]


def _values(rows: list[dict[str, str]], field: str) -> str:
    return " | ".join(_distinct_values(rows, field))


def _distinct_values(rows: list[dict[str, str]], field: str) -> list[str]:
    return sorted({row[field].strip() for row in rows if row[field].strip()})


if __name__ == "__main__":
    main()
