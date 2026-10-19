# Lifecycle period movements

`analyze_period_membership_movements()` is a pure Python service for analysing
already-confirmed `MemberLedgerEntry` evidence. Its period is start-inclusive
and end-exclusive: `[start_date, end_date)`. It does not read exports, match
identities, edit a ledger, or create a report.

The result keeps dated lifecycle actions (`joined`, `reinstated`, `resigned`,
`expelled`) separate from net population change. A join followed by a
resignation in one period is therefore visible as two gross actions while the
net change is zero when the opening and closing countable populations match.

Member Type is reported as the **membership grouping** dimension; Category is
a second independent dimension. A countable-to-countable change in either
dimension creates an outgoing and incoming transfer for that dimension, with
no total-population effect. A countable-to-uncountable snapshot difference
produces `undated_snapshot_change` and an unresolved net change; it does not
place an exit in that quarter. The reviewed `transferred` rule preserves the known countability
state while recording either dimension movement.

Use `EvidenceCorrection` (also available as `LedgerCorrection`) for a reviewed
replacement of one ledger record by another during analysis. A correction
contains the subject key, both immutable record IDs, source references, reason,
and timing. The original evidence stays in the ledger; corrections are neither
lifecycle actions nor population movements. Invalid, cross-subject, duplicate,
or cyclic corrections produce findings rather than changing analysis.

Unknown opening state, unresolved evidence, repeated events which cannot alter
state, and same-day contradictions also produce findings. The service does not
invent movement in those cases. Examples and tests use synthetic records only;
do not add private member evidence to documentation.

Use `knowledge_cutoff` to include evidence available after the period ended.
A supported company `Join Date` places its first join on that date, even when
the supporting snapshot was observed later. Conflicting Join Dates produce a
finding. Activity events use their effective date, then their transaction
date; `dated_actions[].date_basis` records the choice. A snapshot date only
confirms its state on that date.
An explicit same-day reinstatement takes precedence over a Join Date. When an
earlier snapshot confirms membership, a later Join Date is treated as a
reinstatement if the preceding state supports a return to membership. A prior
account snapshot without confirmed membership does not establish that history.
For source dates before the first reviewed rule version, the earliest reviewed
taxonomy interprets the source state or event while the original effective
date remains the movement date.

```python
from datetime import date
from aisc_imis.lifecycle_period_movements import analyze_period_membership_movements

result = analyze_period_membership_movements(
    confirmed_member_entries,
    date(2026, 1, 1),
    date(2026, 2, 1),
    reviewed_rules,
)
```
