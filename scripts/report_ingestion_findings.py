"""Write a local cross-source ingestion findings report for review."""

from __future__ import annotations

import argparse
from pathlib import Path

from aisc_imis.activity_history_records import read_activity_history_records
from aisc_imis.current_member_records import read_current_member_records
from aisc_imis.historical_snapshot_records import read_historical_snapshot_records
from aisc_imis.ingestion_findings import (
    build_ingestion_findings_report,
    write_ingestion_findings_report,
)
from aisc_imis.membership_change_records import read_membership_change_records

DEFAULT_REFERENCE_DIRECTORY = Path("data/reference")
DEFAULT_OUTPUT_DIRECTORY = Path("data/processed/ingestion-findings")


def main() -> None:
    """Read the four caller-selected exports and write two local review reports."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--membership-changes", type=Path, required=True)
    parser.add_argument("--activity-history", type=Path, required=True)
    parser.add_argument(
        "--reference-directory", type=Path, default=DEFAULT_REFERENCE_DIRECTORY
    )
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    args = parser.parse_args()

    report = build_ingestion_findings_report(
        current=read_current_member_records(args.current, args.reference_directory),
        historical=read_historical_snapshot_records(args.history, args.reference_directory),
        membership_changes=read_membership_change_records(
            args.membership_changes, args.reference_directory
        ),
        activity_history=read_activity_history_records(
            args.activity_history, args.reference_directory
        ),
    )
    json_path, markdown_path = write_ingestion_findings_report(
        report, args.output_directory
    )
    print(f"Findings: {len(report.findings):,}")
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {markdown_path}")


if __name__ == "__main__":
    main()
