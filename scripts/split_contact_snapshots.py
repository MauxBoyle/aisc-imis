"""Split combined CSContactBasic records into current and historical CSVs."""

from __future__ import annotations

import argparse
from pathlib import Path

from aisc_imis.contact_snapshots import split_contact_snapshots

DEFAULT_INPUT = Path("data/processed/CSContactBasic_combined_deduplicated.csv")
DEFAULT_CURRENT = Path("data/processed/CSContactBasic_current.csv")
DEFAULT_HISTORY = Path("data/processed/CSContactBasic_history.csv")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT)
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    args = parser.parse_args()

    stats = split_contact_snapshots(args.input, args.current, args.history)

    print(f"Input rows: {stats.input_rows:,}")
    print(f"iMIS IDs: {stats.member_ids:,}")
    print(f"Current rows: {stats.current_rows:,}")
    print(f"Historical rows: {stats.history_rows:,}")
    print(f"Current output: {args.current}")
    print(f"History output: {args.history}")


if __name__ == "__main__":
    main()
