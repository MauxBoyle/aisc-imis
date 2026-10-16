# M5 pending proposals and completed expulsions

`build_m5_expulsions(movements, board_actions)` takes one `QuarterlyMovementResult` from `classify_quarterly_movements()` and the same validated `BoardPendingActions` used by that classifier. It returns `pending_proposals`, `completed_expulsions`, `counts`, and `findings`. Selection does not write files.

The quarter is `[start_date, end_date)`. Pending proposals were proposed during that quarter and still have status `proposed` at the inclusive report cutoff. A proposal has no completed historical event. Rejected and withdrawn expulsion actions appear as findings. Completed rows come from counted M5 classifier movements: eligible Board approvals can count before iMIS updates, and operational expulsions count when their evidence is visible by the report cutoff.

Each row has a member key, Board action ID and status, proposal, approval, effective, and recorded dates, report cutoff, Board document references, lifecycle ledger and source references, and `operational_history`. `recorded` means a counted operational expulsion supports the row. `not_recorded` means the classifier counted a Board decision before operational history confirmed it. A blank action ID means there is no unique Board match. Matching operational evidence uses an explicit iMIS ID from visible Board revisions; multiple matches produce a finding without choosing one. CSV dates use ISO format and missing values are blank.

The builder compares operational completed rows with the balance's `expelled` term, Board only rows with newly applied Board decisions, and all completed rows with counted M5 movements. Differences and incomplete balances remain findings; no balancing rows are invented. Review `result.findings` before using a total.

```python
from aisc_imis.m5_expulsions import build_m5_expulsions, write_m5_csv

# movements is from classify_quarterly_movements(...).
# board_actions is the same validated BoardPendingActions passed to it.
result = build_m5_expulsions(movements, board_actions)
print(result.counts)
for finding in result.findings:
    print(finding.code, finding.message)
write_m5_csv(result, "reports")
```

`write_m5_csv()` writes `m5_pending_proposals.csv` and `m5_completed_expulsions.csv` under the chosen directory. The repository already ignores `reports/`; keep private exports there.
