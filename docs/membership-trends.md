# Explainable membership trends

`build_membership_trends()` compares each neighboring pair of as-of dates. The
first date is the baseline. The function returns structured Python objects;
it does not produce a report or read files. Each period includes its
[operational summary](operational-membership-summaries.md), overall and source
Category rows, findings, and one decision for each relevant member.

This example uses only invented evidence:

```python
from datetime import date

from aisc_imis.evidence_ledger import SnapshotStateObservation
from aisc_imis.lifecycle_rules import load_lifecycle_rules
from aisc_imis.member_ledger import build_member_evidence_ledger
from aisc_imis.membership_trends import build_membership_trends
from aisc_imis.normalization_contracts import SourceReference

baseline = date(2026, 10, 15)
later = date(2026, 10, 20)
source = SourceReference("invented.csv", "row-1")
records = tuple(
    SnapshotStateObservation(
        "example-member-001", f"{field}={value}", source,
        observed_date=baseline, recorded_date=baseline,
    )
    for field, value in (
        ("member_type", "ACT"), ("category", "A"),
        ("is_member", True), ("is_company", False),
    )
)
entries = build_member_evidence_ledger(records).entries
rules = load_lifecycle_rules("data/reference")
trends = build_membership_trends(entries, (baseline, later), ("A", "B"), rules)
period = trends.periods[0]

print(period.overall.opening_count)            # 1
print(period.overall.closing_confirmed_count)  # 1
print(period.overall.closing_count)            # 1
print(period.categories["A"].closing_count)   # 1
print(period.decisions[0].closing_status)      # included
print(period.decisions[0].source_references)   # (SourceReference(...),)
```

Each row has `opening_confirmed_count` and `closing_confirmed_count`: the
number of members supported by boundary evidence. `opening_count` and
`closing_count` are definitive only when the evidence is complete; otherwise
they are `None`. `movements` holds classified lifecycle action counts, and
`transfers_in` and `transfers_out` show Category changes. A Category transfer
does not change the overall count. `net_change` is the definitive closing
count minus the definitive opening count, or `None` if either is unknown.
`expected_closing` and `difference` come from the existing balance equation.
A nonzero difference is a finding, not an invented movement.

Use `row.terms` to trace each opening, closing, or movement count to members.
Each `BalanceTermEvidence` has a `subject_key` and supporting ledger evidence.
`period.decisions` explains those members' opening and closing states,
Category and Member Type codes, lifecycle actions, transfers, findings,
applied corrections, retained ledger evidence, and source row references.
`closing_status` is `included`, `excluded`, or `uncertain`; `inclusion_reason`
explains that decision. A countable closing state can still be `uncertain`
when unresolved period evidence prevents a confirmed inclusion.

Pass at least two strictly increasing `date` values. A later date creates a
period covering the day after the preceding cutoff through that later date.
Categories are source codes and must be unique and nonblank. The service does
not combine Member Types, resolve conflicting evidence, or accept Board
adjustments. Keep real member evidence in authorized local storage.
