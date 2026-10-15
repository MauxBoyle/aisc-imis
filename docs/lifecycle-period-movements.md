# Lifecycle period movements

`analyze_period_membership_movements()` is a pure Python service for analysing
already-confirmed `MemberLedgerEntry` evidence. Its period is start-inclusive
and end-exclusive: `[start_date, end_date)`. It does not read exports, match
identities, edit a ledger, or create a report.

The result keeps gross lifecycle actions (`joined`, `reinstated`, `resigned`,
`expelled`, and inferred snapshot `exited`) separate from net population change. A join followed by a
resignation in one period is therefore visible as two gross actions while the
net change is zero when the opening and closing countable populations match.

Member Type is reported as the **membership grouping** dimension; Category is
a second independent dimension. A countable-to-countable change in either
dimension creates an outgoing and incoming transfer for that dimension, with
no total-population effect. A countable-to-uncountable snapshot change creates
an `exited` action, not a transfer. The reviewed `transferred` rule preserves the known countability
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
