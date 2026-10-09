"""Generate iMIS reference tables from a company export."""

from __future__ import annotations

import argparse
from pathlib import Path

from aisc_imis.reference import write_reference_tables


def main() -> None:
    """Parse arguments and generate the reference CSV files."""
    parser = argparse.ArgumentParser(
        description="Generate iMIS reference tables from a company CSV export."
    )
    parser.add_argument("input_csv", type=Path, help="Path to the iMIS company export.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/reference"),
        help="Directory for generated reference tables (default: data/reference).",
    )
    args = parser.parse_args()

    for output_path in write_reference_tables(args.input_csv, args.output_dir):
        print(output_path)


if __name__ == "__main__":
    main()
