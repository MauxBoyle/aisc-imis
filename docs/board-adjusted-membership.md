# Board-adjusted membership view

`build_board_adjusted_membership(operational, pending)` combines an
`OperationalMembershipSummary` with validated `BoardPendingActions`. It is a
pure, read-only function. The result has three side-by-side parts:

| Field | Meaning |
| --- | --- |
| `operational` | The original summary, including its evidence, balance, and findings. |
| `adjustments` | Signed changes to confirmed overall, Category, and Member Type counts. |
| `adjusted` | Board-adjusted counts and member contributors; `total` is `None` if definitive coverage is missing. |

`decisions` lists each action's selected revision, matched subject key, status,
disposition, reason, and source document. `findings` explains skipped actions,
unconfirmed iMIS recording, and missing breakdown values. Keep this result in
ignored local storage when it contains real member data.

## Date and matching rules

The summary's `as_of_date` is the inclusive cutoff. The latest revision whose
`status_date` is on or before that date controls the action. A later revision
does not change an earlier view. Only an approved action can change counts;
both its approval `status_date` and its `effective_date` must be within the
cutoff. If `effective_date` is absent, the approval date is used. Proposed,
rejected, and withdrawn actions stay visible with no adjustment.

An action with `imis_id` matches that exact operational subject key. Otherwise
`member_ref` matches the exact subject key. An unmatched approved new-member
action creates a Board-only contributor. An unmatched expulsion or correction
is skipped because its prior member state cannot be established. A member
whose operational state is uncertain is also skipped. Possible duplicate
actions and competing eligible actions for one subject are flagged and skipped.

For `recorded-in-iMIS`, the prior approved revision remains the overlay until
the operational state confirms the requested change. The view then stops the
overlay, so the member is counted only through the operational summary. A
record reference alone does not confirm the change.

An unmatched approved addition without Category or Member Type raises the overall
confirmed count. Its Category and Member Type totals stay `None`, with findings
explaining the missing values. An indeterminate operational total remains
indeterminate in the Board view. The original operational evidence and balance
are never edited.

## Synthetic trace

Assume an invented operational summary for October 20 has one confirmed member
and an overall total of `1`. A validated `new-member-approval` for
`invented-new-member` was approved October 18, with no effective date or iMIS
record. Calling the function gives this result:

```python
from aisc_imis.board_adjusted_membership import build_board_adjusted_membership

view = build_board_adjusted_membership(operational, pending)
print(view.operational.overall.total)  # 1
print(view.decisions[0].disposition)  # "applied"
print(view.adjustments.overall)       # 1
print(view.adjusted.overall.total)    # 2
```

Here `operational` and `pending` are the two validated objects described in
[operational summaries](operational-membership-summaries.md) and
[pending Board actions](board-pending-actions.md). The decision also retains
the action ID, approval reason, and source document. With no Category or Member
Type on that new member, the corresponding adjusted breakdown totals are
`None`.
