"""Generate an aggregate-only identifier map for the four membership exports."""

from __future__ import annotations

import argparse
from pathlib import Path

from aisc_imis.identifier_discovery import (
    IdentifierComparison,
    IdentifierSource,
    build_identifier_map,
    render_markdown,
)


def default_sources() -> tuple[IdentifierSource, ...]:
    """Return the four reviewed membership exports and identifier columns."""
    return (
        IdentifierSource(
            "Current records",
            Path("data/processed/CSContactBasic_current.csv"),
            ("iMIS Id", "Major Key", "Company ID"),
        ),
        IdentifierSource(
            "CSContactBasic history",
            Path("data/processed/CSContactBasic_history.csv"),
            ("iMIS Id", "Major Key", "Company ID"),
        ),
        IdentifierSource(
            "Membership changes",
            Path("data/raw/imisChanges3years_261014.csv"),
            ("ChangeID", "Ordinal"),
        ),
        IdentifierSource(
            "Activity history",
            Path("data/raw/imis_Activity_historyDetail_202610.csv"),
            ("iMIS Id", "Sequence"),
        ),
    )


def exact_comparisons() -> tuple[IdentifierComparison, ...]:
    """Return only identifier relationships supported for exact matching."""
    return (
        IdentifierComparison(
            "Current records iMIS Id ↔ CSContactBasic history iMIS Id",
            "Current records",
            "iMIS Id",
            "CSContactBasic history",
            "iMIS Id",
            "exact member identifier",
        ),
        IdentifierComparison(
            "Current records iMIS Id ↔ activity history iMIS Id",
            "Current records",
            "iMIS Id",
            "Activity history",
            "iMIS Id",
            "exact member identifier",
        ),
        IdentifierComparison(
            "CSContactBasic history iMIS Id ↔ activity history iMIS Id",
            "CSContactBasic history",
            "iMIS Id",
            "Activity history",
            "iMIS Id",
            "exact member identifier",
        ),
        IdentifierComparison(
            "Current records Major Key → current records iMIS Id",
            "Current records",
            "Major Key",
            "Current records",
            "iMIS Id",
            "parent/dependent evidence",
        ),
        IdentifierComparison(
            "CSContactBasic history Major Key → CSContactBasic history iMIS Id",
            "CSContactBasic history",
            "Major Key",
            "CSContactBasic history",
            "iMIS Id",
            "parent/dependent evidence",
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("docs/member-identifier-map.md")
    )
    arguments = parser.parse_args()
    identifier_map = build_identifier_map(default_sources(), exact_comparisons())
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(render_markdown(identifier_map), encoding="utf-8")


if __name__ == "__main__":
    main()
