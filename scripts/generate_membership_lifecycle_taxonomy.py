"""Generate aggregate lifecycle-evidence documentation and its review matrix."""

from __future__ import annotations

import argparse
from pathlib import Path

from aisc_imis.lifecycle_discovery import (
    LifecycleField,
    LifecycleSource,
    UsefulCombination,
    build_lifecycle_profile,
    render_markdown,
    write_evidence_matrix,
)


def default_sources() -> tuple[LifecycleSource, ...]:
    """Return the reviewed code fields in the four authorized local exports."""
    snapshot_fields = (
        LifecycleField("Member Type", "state observation", "direct fact"),
        LifecycleField("Member Status", "state observation", "direct fact"),
        LifecycleField("Status", "state observation", "direct fact"),
        LifecycleField("Category", "state observation", "direct fact"),
        LifecycleField("Is Member", "state observation", "direct fact"),
        LifecycleField("Is Company", "state observation", "direct fact"),
    )
    return (
        LifecycleSource(
            "Current records",
            Path("data/processed/CSContactBasic_current.csv"),
            snapshot_fields,
            (UsefulCombination("Member type and status", ("Member Type", "Status")),),
        ),
        LifecycleSource(
            "CSContactBasic history",
            Path("data/processed/CSContactBasic_history.csv"),
            snapshot_fields,
            (UsefulCombination("Member type and status", ("Member Type", "Status")),),
        ),
        LifecycleSource(
            "Membership changes",
            Path("data/raw/imisChanges3years_261014.csv"),
            (
                LifecycleField(
                    "Change Type", "lifecycle-event candidate", "possible inference"
                ),
                LifecycleField("Member Type", "state observation", "direct fact"),
                LifecycleField("Member Status", "state observation", "direct fact"),
                LifecycleField("Status", "state observation", "direct fact"),
                LifecycleField("Category", "state observation", "direct fact"),
                LifecycleField("Is Company", "state observation", "direct fact"),
                LifecycleField(
                    "Paid Through",
                    "payment activity",
                    "direct fact",
                    publish_values=False,
                ),
            ),
            (
                UsefulCombination(
                    "Change type, member type, and status",
                    ("Change Type", "Member Type", "Status"),
                ),
            ),
        ),
        LifecycleSource(
            "Activity history",
            Path("data/raw/imis_Activity_historyDetail_202610.csv"),
            (
                LifecycleField(
                    "A_Transaction", "metadata", "direct fact", publish_values=False
                ),
                LifecycleField("Activity Type", "unknown", "possible inference"),
                LifecycleField("Member Type", "state observation", "direct fact"),
                LifecycleField("ContactCategory", "unknown", "possible inference"),
                LifecycleField("ActivityCategory", "unknown", "possible inference"),
                LifecycleField(
                    "Action Codes",
                    "unknown",
                    "possible inference",
                    publish_values=False,
                ),
                LifecycleField("Entity Code", "unknown", "possible inference"),
                LifecycleField(
                    "Other Code", "unknown", "possible inference", publish_values=False
                ),
                LifecycleField(
                    "Product Code",
                    "unknown",
                    "possible inference",
                    publish_values=False,
                ),
                LifecycleField(
                    "Source Code", "unknown", "possible inference", publish_values=False
                ),
                LifecycleField("Is a Company", "state observation", "direct fact"),
            ),
            (
                UsefulCombination(
                    "Activity type, category, and entity code",
                    ("Activity Type", "ActivityCategory", "Entity Code"),
                ),
            ),
        ),
    )


def main() -> None:
    """Regenerate both committed lifecycle-taxonomy outputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--matrix",
        type=Path,
        default=Path("data/reference/lifecycle-evidence-taxonomy.csv"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("docs/membership-lifecycle-taxonomy.md")
    )
    arguments = parser.parse_args()
    profile = build_lifecycle_profile(default_sources())
    write_evidence_matrix(profile, arguments.matrix)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(render_markdown(profile), encoding="utf-8")


if __name__ == "__main__":
    main()
