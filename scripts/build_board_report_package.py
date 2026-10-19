"""Build a local Board report package from explicit source paths."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from aisc_imis.board_report_package import BoardReportInputs, build_board_report_package


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("period_start", "as_of_date", "board_cutoff", "current_export_date"):
        parser.add_argument(
            f"--{name.replace('_', '-')}", required=True, type=date.fromisoformat
        )
    for name in (
        "current_csv",
        "history_csv",
        "membership_changes_csv",
        "activity_history_csv",
        "new_members_iqa_csv",
        "board_actions_json",
        "review_registry_json",
        "reference_directory",
        "output_directory",
    ):
        parser.add_argument(f"--{name.replace('_', '-')}", required=True, type=Path)
    result = build_board_report_package(
        BoardReportInputs(**vars(parser.parse_args())),
        progress=lambda message: print(message, file=sys.stderr, flush=True),
    )
    print(f"Run ID: {result.run_id}")
    print(f"Findings: {result.finding_count}")
    for path in result.output_files:
        print(path)


if __name__ == "__main__":
    main()
