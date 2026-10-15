"""Combine and de-duplicate CSContactBasic snapshot CSV files."""

from __future__ import annotations

import argparse
from pathlib import Path

from aisc_imis.contact_snapshots import combine_contact_snapshots, find_snapshot_files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/CSContactBasic_combined_deduplicated.csv"),
    )
    args = parser.parse_args()

    input_paths = find_snapshot_files(args.input_dir)
    if args.output.exists() and args.output not in input_paths:
        input_paths.insert(0, args.output)
    stats = combine_contact_snapshots(input_paths, args.output)

    print(f"Input files: {stats.input_files:,}")
    print(f"Input rows: {stats.input_rows:,}")
    print(f"Rows after exact de-duplication: {stats.exact_unique_rows:,}")
    print(f"Rows additionally coalesced: {stats.coalesced_rows:,}")
    print(f"Output rows: {stats.output_rows:,}")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
