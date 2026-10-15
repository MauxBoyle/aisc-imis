"""Contract checks for the privacy-safe membership-history design baseline."""

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_membership_history_architecture_is_navigable_and_complete():
    """Keep the design page discoverable and explicit about its open rules."""
    document = ROOT / "docs" / "membership-history-architecture.md"
    markdown = document.read_text(encoding="utf-8")
    navigation = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")

    assert "Membership History Architecture: membership-history-architecture.md" in navigation

    required_topics = (
        "## Evidence and provenance",
        "## Proposed normalized record shapes",
        "## Status at a date",
        "## Opening state and incomplete history",
        "## Operational reconstruction and Board adjustments",
        "## Data ownership and privacy",
        "## Open decisions, risks, and downstream issues",
        "observed evidence",
        "inferred history",
        "operational state",
        "Board adjustment",
        "candidate event",
        "snapshot observation",
        "state interval",
        "finding",
        "recorded date",
        "observation date",
        "unknown before coverage",
        "immutable",
        "reversible overlay",
        "parent tracker (#7)",
    )
    for topic in required_topics:
        assert topic in markdown

    for issue_number in range(13, 40):
        assert f"#{issue_number}" in markdown
