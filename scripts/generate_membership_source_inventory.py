"""Generate the aggregate-only membership source inventory Markdown file."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from aisc_imis.source_inventory import (
    SourceDefinition,
    build_inventory,
    render_markdown,
)


def default_sources() -> tuple[SourceDefinition, ...]:
    """Return the four reviewed membership inputs and their known schema checks."""
    return (
        SourceDefinition(
            name="Current records",
            path=Path("data/processed/CSContactBasic_current.csv"),
            source_type="current-state export",
            candidate_key=("iMIS Id",),
            date_columns=("Date Added", "Join Date", "Last Updated"),
            required_columns=("iMIS Id", "Date Added", "Join Date", "Last Updated"),
            extraction_note="Newest CSContactBasic row per iMIS Id, derived by scripts/split_contact_snapshots.py.",
        ),
        SourceDefinition(
            name="CSContactBasic history",
            path=Path("data/processed/CSContactBasic_history.csv"),
            source_type="historical snapshot observations",
            candidate_key=("iMIS Id", "Last Updated"),
            date_columns=("Date Added", "Join Date", "Last Updated"),
            required_columns=("iMIS Id", "Date Added", "Join Date", "Last Updated"),
            extraction_note="Older CSContactBasic rows after the newest row per iMIS Id is separated by scripts/split_contact_snapshots.py; this is not assumed complete history.",
        ),
        SourceDefinition(
            name="Membership changes",
            path=Path("data/raw/imisChanges3years_261014.csv"),
            source_type="membership-change transaction history",
            candidate_key=("ChangeID", "Ordinal"),
            date_columns=(
                "ChangeUpdate",
                "ChangeCreated",
                "ChangeEffective",
                "Thru Date",
                "ContactUpdateLast",
                "Member Status Date",
                "Paid Through",
                "ContactUpdated",
            ),
            required_columns=(
                "ChangeID",
                "Ordinal",
                "ChangeUpdate",
                "ChangeCreated",
                "ChangeEffective",
            ),
            extraction_note="Local raw export named imisChanges3years_261014.csv; no additional row filtering is applied by the inventory.",
        ),
        SourceDefinition(
            name="Activity history",
            path=Path("data/raw/imis_Activity_historyDetail_202610.csv"),
            source_type="activity transaction history",
            candidate_key=("iMIS Id", "Sequence"),
            date_columns=("Effective Date", "Transaction Date"),
            required_columns=(
                "iMIS Id",
                "Sequence",
                "Effective Date",
                "Transaction Date",
            ),
            extraction_note="Local raw export named imis_Activity_historyDetail_202610.csv; no additional row filtering is applied by the inventory.",
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("docs/membership-source-inventory.md")
    )
    parser.add_argument(
        "--reference-date",
        type=date.fromisoformat,
        default=date.today(),
        help="Latest plausible date, in ISO format (default: today).",
    )
    arguments = parser.parse_args()
    inventory = build_inventory(
        default_sources(), reference_date=arguments.reference_date
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(render_markdown(inventory), encoding="utf-8")


if __name__ == "__main__":
    main()
