"""Reconcile Salesforce Certified Domestic Fabricators with iMIS companies."""

from __future__ import annotations

import argparse
from pathlib import Path

from aisc_imis.reconciliation import (
    read_imis_records,
    read_salesforce_records,
    reconcile_records,
    write_reconciliation_reports,
)


def main() -> None:
    """Parse input paths and write the reconciliation CSV and PDF reports."""
    parser = argparse.ArgumentParser(
        description="Reconcile Salesforce Certified Domestic Fabricators with iMIS."
    )
    parser.add_argument("salesforce_csv", type=Path, help="Path to the Salesforce CSV export.")
    parser.add_argument("imis_csv", type=Path, help="Path to the iMIS CSV export.")
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--address-threshold", type=float, default=90)
    parser.add_argument("--name-threshold", type=float, default=50)
    args = parser.parse_args()

    results = reconcile_records(
        read_salesforce_records(args.salesforce_csv),
        read_imis_records(args.imis_csv),
        address_threshold=args.address_threshold,
        name_threshold=args.name_threshold,
    )
    csv_path, pdf_path = write_reconciliation_reports(
        results,
        args.output_dir,
        address_threshold=args.address_threshold,
        name_threshold=args.name_threshold,
    )
    print(csv_path)
    print(pdf_path)


if __name__ == "__main__":
    main()
