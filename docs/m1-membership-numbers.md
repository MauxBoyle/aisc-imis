# M1 membership numbers

`build_m1_membership_numbers(balance, opening_board, closing_board, board_cutoff)`
returns a typed `M1MembershipNumbers` result with an `overall` row and one row
per requested source Category code. Build the balance with
`reconcile_membership_balance()` and the two Board views with
`build_board_adjusted_membership()`. Use the same ledger, rules, Category codes,
and inclusive Board cutoff for all three inputs.

The reporting period is half-open: `[start_date, end_date)`. The opening view is
as of `start_date - 1 day`. The closing operational view is as of
`end_date - 1 day`; an event effective on `end_date` belongs to the next
period. The Board cutoff can be later than that operational as-of date and is
inclusive. It controls which Board approvals and recorded evidence are known.
The builder checks view dates, cutoff, Category codes, and known operational
totals against the balance.

Each `M1Row` has these fields:

| Fields | Meaning |
| --- | --- |
| `start_date`, `end_date`, `operational_as_of_date`, `board_cutoff` | Period and separate operational and Board dates. |
| `category` | Source Category code; `None` means overall. |
| `operational_opening`, `joined`, `reinstated`, `resigned`, `expelled`, `exited`, `transfers_in`, `transfers_out` | Operational opening and classified period movements. Transfers cancel in the overall row. |
| `reviewed_adjustments` | Signed, explicitly reviewed balance adjustments. |
| `operational_expected_closing`, `operational_closing`, `operational_difference` | Expected count, observed count, and `closing - expected`. |
| `board_opening_adjustment`, `board_closing_adjustment`, `board_adjustment_change` | Signed Board overlays on the opening and closing counts and their change. |
| `board_adjusted_opening`, `board_adjusted_expected_closing`, `board_adjusted_closing`, `board_adjusted_difference` | Board adjusted equation. Expected closing equals operational expected closing plus the closing Board adjustment. |
| `status` | `reconciled`, `unresolved_unknown`, or `unresolved_difference`. |

The result also carries `start_date`, `end_date`, `operational_as_of_date`, and
`board_cutoff`. An unknown count remains `None`; its CSV cell is blank. Confirmed
movements and signed Board adjustments can still be shown. If a short opening
Board view lacks its own prior baseline, the known period balance supplies the
opening total when its confirmed count agrees. Board Category gaps still leave
the Category total unknown. A nonzero difference remains in both the typed row
and CSV. It is **never** turned into an adjustment.

Once you have a verified `balance`, `opening_board`, and `closing_board`:

```python
from datetime import date
from aisc_imis.m1_membership_numbers import (
    build_m1_membership_numbers,
    write_m1_csv,
)

m1 = build_m1_membership_numbers(
    balance, opening_board, closing_board, date(2027, 4, 15)
)
print(m1.overall.status, m1.overall.operational_difference)
write_m1_csv(m1, "reports/m1-2027-q1.csv")  # Create reports/ first.
```

The writer creates one aggregate row for overall and each Category. It does not
include member identities or evidence. A shortened CSV example:

```csv
start_date,end_date,operational_as_of_date,board_cutoff,category,operational_opening,reviewed_adjustments,operational_difference,board_adjusted_closing,status
2027-01-01,2027-04-01,2027-03-31,2027-04-15,,1,1,-1,3,unresolved_difference
2027-01-01,2027-04-01,2027-03-31,2027-04-15,A,1,1,-1,1,unresolved_difference
```

The actual CSV contains every `M1Row` field, including all movement counts.
`reports/` is ignored by Git for local output.
