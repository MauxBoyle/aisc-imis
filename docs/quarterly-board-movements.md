# Quarterly Board movements (M2–M5)

`classify_quarterly_movements` builds a read-only classification from member ledger entries, reviewed lifecycle rules, and validated `BoardPendingActions`. It takes a period `[start_date, end_date)`, an **inclusive** `report_cutoff`, Category codes, and optional evidence corrections. The cutoff must be on or after the period's last day.

The effective date places a movement in the period. The recorded date decides whether an iMIS record was known by the report cutoff. If a record has no recorded date, its observed date is used. Board revisions must be known by the cutoff; an approval also needs an effective date within the view date. A later iMIS recording of the same Board action does not create another movement.

The result contains `counted` member rows, `noncounted` visible Board rows, `operational_total_change`, `board_adjusted_total_change`, the operational balance, opening and closing Board views, transfers, applied corrections, and findings. Counted rows include the M2–M5 measure, action, effective date, available proposed/approved/recorded dates, reason, and ledger evidence or Board action ID and document reference. Every noncounted Board row has a reason. `None` means a total cannot be established from the evidence.

By default, joins use M2. Pass `join_measures={"ASSOC": "M3"}` to assign a Member Type to M3. For a Board-only join, put `"member_type": "ASSOC"` on its approved new-member revision. If it is absent or unmapped, that join uses M2. Resignations and reinstatements use M4; expulsions use M5. Category and Member Type transfers remain separate from joins and exits. Board corrections stay visible as separate, noncounted actions and affect the Board views when eligible.

```python
from datetime import date

from aisc_imis.board_pending_actions import BoardPendingActions
from aisc_imis.quarterly_board_movements import classify_quarterly_movements

# Invented records and reviewed rules supplied by the caller.
result = classify_quarterly_movements(
    entries=ledger.entries,
    start_date=date(2027, 1, 1),
    end_date=date(2027, 4, 1),
    report_cutoff=date(2027, 4, 15),
    rules=rules,
    board_actions=BoardPendingActions((), ()),
    categories=("A", "B"),
)
for row in result.counted:
    print(row.subject_key, row.measure, row.effective_date, row.recorded_date)
```

For example, an invented join effective March 31 and recorded April 10 belongs to the first quarter when the report cutoff is April 15. It is absent with an April 5 cutoff. An April 1 effective date belongs to the next period.
