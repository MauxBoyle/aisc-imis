# Operational membership summaries

`summarize_operational_membership()` returns membership counts for one requested
date from already-built member ledger entries. It uses the reviewed lifecycle
rules in `data/reference/` and performs no file reads or writes.

Pass an explicit `prior_as_of_date`. The reconciliation period starts **the day
after** that cutoff and includes the `as_of_date`. For example, a prior cutoff
of October 15 and an as-of date of October 20 reconcile October 16–20. An
event or snapshot dated October 20 is included. The function returns the
existing [period balance](period-membership-balance.md) in `result.balance`;
its `overall.difference` and per-Category differences are never silently
converted into adjustments. The summary does not accept Board adjustments.
Members whose first dated lifecycle evidence is after the as-of date do not
enter that earlier summary.
The period's member-level movement analysis is also available as
`result.movement`; the [trends service](membership-trends.md) uses it for
decision records.

This synthetic example builds a small ledger in memory:

```python
from datetime import date

from aisc_imis.evidence_ledger import SnapshotStateObservation
from aisc_imis.lifecycle_rules import load_lifecycle_rules
from aisc_imis.member_ledger import build_member_evidence_ledger
from aisc_imis.normalization_contracts import SourceReference
from aisc_imis.operational_membership_summary import (
    summarize_operational_membership,
)

observed = date(2026, 10, 15)
source = SourceReference("invented.csv", "row-1")
records = tuple(
    SnapshotStateObservation(
        "example-member-001", f"{field}={value}", source,
        observed_date=observed, recorded_date=observed,
    )
    for field, value in (
        ("member_type", "ACT"), ("category", "A"),
        ("is_member", True), ("is_company", False),
    )
)
entries = build_member_evidence_ledger(records).entries
rules = load_lifecycle_rules("data/reference")
result = summarize_operational_membership(
    entries, date(2026, 10, 31), date(2026, 10, 15), ("A", "B"), rules,
)
print(result.overall.total)  # 1
print(result.categories["A"].confirmed_count)  # 1
print(result.member_types["ACT"].contributors[0].subject_key)
print(result.balance.overall.difference)  # 0
```

`overall`, `categories`, and `member_types` each provide a `confirmed_count`,
a `total`, and member-level `contributors`. Each contributor includes the member
ID, source Category and Member Type codes, supporting ledger records, and any
applied evidence corrections. Codes are not renamed or combined. The selected
Category codes appear even when their count is zero. Member Type keys are
drawn from the evidence observed at the period boundaries.

`confirmed_count` counts members with a supported, countable closing state. A
`total` of `None` means the calculation cannot claim a definitive count: for
example, a member's opening or closing state is unknown, lifecycle evidence is
unresolved, or a countable member lacks a needed breakdown code. In that case,
confirmed contributors and findings remain visible. `unknown_member_ids`,
`missing_category_member_ids`, and `missing_member_type_member_ids` identify
coverage gaps. Inspect `result.findings` and the balance differences before
using a count. A `None` balance difference means reconciliation is
indeterminate; a nonzero difference is a finding to investigate.

`select_reporting_month_ends(start_date, end_date)` returns calendar month ends
inside an inclusive date range. Pass `quarter_ends_only=True` to select March,
June, September, and December ends. Custom as-of dates need no selector; pass
the date and its explicit prior cutoff directly to the summary function.

Keep real ledger inputs and any exported results in ignored local operational
storage. Examples and tests contain invented members only.
