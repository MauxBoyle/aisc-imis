# M4 resignations and reinstatements

Each output row includes `date_basis` to identify the event effective or
transaction date used for the movement.

`build_m4_resignations_reinstatements(movements)` takes a `QuarterlyMovementResult` from `classify_quarterly_movements()` and selects its counted M4 resignations and reinstatements. It returns separate `resignations` and `reinstatements` tuples, `counts`, and `findings`. Selection is pure: it does not write files or change the classifier result.

The classifier's period is `[start_date, end_date)`: the effective date places an action in the period, and the recorded date determines whether the evidence was known by the inclusive `report_cutoff`. If a recorded date is absent, the classifier uses the observed date. A resignation followed by reinstatement in the same period appears once in each list. Category and Member Type transfers are separate movements. Each M4 row keeps the Category and Member Type at its action.

Each row has `subject_key`, `action`, `effective_date`, `recorded_date`, `report_cutoff`, `category`, `member_type`, `operational_status`, and `ledger_evidence_refs`. The resulting operational status is `former_member` for resignation and `current_member` for reinstatement. References include ledger record IDs and source rows. Missing dates or attributes are blank in the CSV. A row requires a matching lifecycle event, or a Join Date with an earlier member snapshot for an inferred reinstatement.

`write_m4_csv(result, output_dir)` writes `m4_resignations.csv` and `m4_reinstatements.csv` under the chosen directory, normally ignored `reports/`. Both files use the fields above as headers and are ordered by effective date and member key.

The builder compares each list length with the classifier's counted M4 actions and the corresponding `resigned` or `reinstated` term in `movements.operational_balance.overall.movements`. A mismatch becomes a finding. Classifier and balance findings, including unresolved or conflicting evidence and incomplete balances, remain in `result.findings`. Review them before using totals; the builder never creates an action to force a balance to agree. An incomplete balance keeps its `difference` as `None` in the original classifier result.

```python
from aisc_imis.m4_resignations_reinstatements import (
    build_m4_resignations_reinstatements,
    write_m4_csv,
)

# movements is the result of classify_quarterly_movements(...).
result = build_m4_resignations_reinstatements(movements)
print(result.counts)
for finding in result.findings:
    print(finding.code, finding.message)
write_m4_csv(result, "reports")
```
