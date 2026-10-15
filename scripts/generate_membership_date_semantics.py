"""Generate aggregate-only date-semantics evidence for membership exports."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from aisc_imis.date_discovery import (
    DateField,
    DatePair,
    DateSource,
    build_date_profile,
    render_markdown,
)


def default_sources() -> tuple[DateSource, ...]:
    """Return every candidate date field in the four reviewed source schemas."""
    contact_fields = (
        DateField(
            "Date Added",
            "Recorded/create-date candidate",
            "It may be a contact-record creation date rather than a membership date.",
        ),
        DateField(
            "Join Date",
            "Candidate membership effective date",
            "Confirm its business definition before using it for membership ordering.",
        ),
        DateField(
            "Last Updated",
            "Recorded/update-date candidate",
            "It records an update observation, not necessarily an effective change.",
        ),
    )
    return (
        DateSource(
            "Current records",
            Path("data/processed/CSContactBasic_current.csv"),
            contact_fields,
            (DatePair("Join Date compared with Date Added", "Join Date", "Date Added"),),
        ),
        DateSource(
            "CSContactBasic history",
            Path("data/processed/CSContactBasic_history.csv"),
            contact_fields,
            (DatePair("Join Date compared with Date Added", "Join Date", "Date Added"),),
        ),
        DateSource(
            "Membership changes",
            Path("data/raw/imisChanges3years_261014.csv"),
            (
                DateField(
                    "ChangeUpdate",
                    "Recorded/update-date candidate",
                    "It may be transaction maintenance timing, not effective timing.",
                ),
                DateField(
                    "ChangeCreated",
                    "Recorded/create-date candidate",
                    "Its relation to transaction entry and business effect needs validation.",
                ),
                DateField(
                    "ChangeEffective",
                    "Candidate effective date",
                    "Validate the covered event and backdating rules before effective ordering.",
                ),
                DateField(
                    "Thru Date",
                    "Open question: through/end date",
                    "It may represent entitlement, billing, or another interval boundary.",
                ),
                DateField(
                    "ContactUpdateLast",
                    "Contact update-date candidate",
                    "Do not treat a contact update as membership timing without validation.",
                ),
                DateField(
                    "Member Status Date",
                    "Candidate membership-status effective date",
                    "Confirm which status change it records and whether it is backdated.",
                ),
                DateField(
                    "Paid Through",
                    "Open question: payment/through date",
                    "It is not assumed to be an effective membership date.",
                ),
                DateField(
                    "ContactUpdated",
                    "Contact update-date candidate",
                    "Do not conflate contact maintenance with membership events.",
                ),
            ),
            (
                DatePair(
                    "ChangeEffective compared with ChangeCreated",
                    "ChangeEffective",
                    "ChangeCreated",
                ),
                DatePair(
                    "ChangeEffective compared with ChangeUpdate",
                    "ChangeEffective",
                    "ChangeUpdate",
                ),
                DatePair(
                    "Member Status Date compared with ChangeEffective",
                    "Member Status Date",
                    "ChangeEffective",
                ),
            ),
        ),
        DateSource(
            "Activity history",
            Path("data/raw/imis_Activity_historyDetail_202610.csv"),
            (
                DateField(
                    "Effective Date",
                    "Candidate effective date",
                    "Validate the activity type and business effect before using it for ordering.",
                ),
                DateField(
                    "Transaction Date",
                    "Recorded/transaction-date candidate",
                    "Preserve it as provenance rather than assuming it is effective timing.",
                ),
            ),
            (
                DatePair(
                    "Effective Date compared with Transaction Date",
                    "Effective Date",
                    "Transaction Date",
                ),
            ),
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("docs/membership-date-semantics.md")
    )
    parser.add_argument(
        "--reference-date",
        type=date.fromisoformat,
        default=date.today(),
        help="Latest plausible date, in ISO format (default: today).",
    )
    arguments = parser.parse_args()
    profile = build_date_profile(
        default_sources(), reference_date=arguments.reference_date
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(render_markdown(profile), encoding="utf-8")


if __name__ == "__main__":
    main()
