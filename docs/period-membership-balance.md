# Period membership balance

`reconcile_membership_balance()` compares confirmed member evidence in a period
`[start_date, end_date)`. Give it the same ledger entries and reviewed lifecycle
rules used by the [period movement analysis](lifecycle-period-movements.md),
plus the source Category codes to report.

For the overall population and each selected Category, it calculates:

```text
expected closing = opening + joined + reinstated - resigned - expelled
                   - exited + transfers in - transfers out + reviewed adjustments
difference = closing - expected closing
```

Category transfers contribute one out and one in. They cancel for the overall
population. The result's `overall` and `categories` contain the counts and
`terms`: member-level entries with dates and supporting ledger records. Its
`findings` explain nonzero differences and evidence that could not be assigned
to a confirmed movement. A nonzero difference is **never** entered as an
adjustment automatically.

Corrections replace specific ledger evidence during analysis. They can change
opening or closing countability, but they are not movements or adjustments.
`ReviewedBalanceAdjustment` is separate: it requires a member key, effective
date inside the period, source Category code, signed nonzero count, reason, and
source references. Its signed count changes the expected closing count.

When any member's opening or closing countability is unknown, `complete` is
false and the overall opening, closing, expected closing, and difference are
`None`. Confirmed movements and findings remain visible. A missing Category
for a countable member or movement leaves Category balances incomplete while
the overall balance can still be calculated. Source Category codes are used
without renaming or grouping them.

```python
from datetime import date
from aisc_imis.period_membership_balance import reconcile_membership_balance

result = reconcile_membership_balance(
    confirmed_ledger_entries,
    date(2026, 1, 1),
    date(2026, 2, 1),
    ("A", "B"),
    reviewed_rules,
)
print(result.overall.difference)
print(result.categories["A"].terms["opening"])
```

The API is a pure calculation. It does not read private exports or write a
report. The tests use synthetic members only.
