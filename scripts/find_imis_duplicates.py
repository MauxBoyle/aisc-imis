"""Create iMIS duplicate-company candidate reports from a company export."""

from __future__ import annotations

import argparse
from pathlib import Path

from aisc_imis.duplicates import find_duplicate_candidates, write_duplicate_reports


def main() -> None:
    """Parse arguments, find candidates, and write CSV and PDF reports."""
    parser = argparse.ArgumentParser(
        description="Find likely duplicate company records in an iMIS CSV export."
    )
    parser.add_argument(
        "input_csv",
        nargs="?",
        type=Path,
        default=Path("data/raw/All_iMIS_Companies_261009.csv"),
        help="Path to the iMIS company export.",
    )
    parser.add_argument("--mode", choices=("all", "act"), default="all")
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--address-threshold", type=float, default=90)
    parser.add_argument("--name-threshold", type=float, default=85)
    args = parser.parse_args()

    candidates = find_duplicate_candidates(
        args.input_csv,
        mode=args.mode,
        address_threshold=args.address_threshold,
        name_threshold=args.name_threshold,
    )
    csv_path, pdf_path = write_duplicate_reports(
        candidates,
        args.output_dir,
        mode=args.mode,
        address_threshold=args.address_threshold,
        name_threshold=args.name_threshold,
    )
    print(csv_path)
    print(pdf_path)


if __name__ == "__main__":
    main()
