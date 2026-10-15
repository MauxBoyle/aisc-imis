# Reconciliation finding taxonomy

`aisc_imis.finding_taxonomy` turns a known lifecycle or reconciliation code into
a structured item for review. It does not recalculate membership state. Existing
rule, reconstruction, and movement results remain the source of operational
decisions; callers create a finding alongside them.

| Type | Default severity | Representative codes | Reviewer action |
| --- | --- | --- | --- |
| Information gap | Info | `missing_lifecycle_date`, `unknown_starting_state`, `missing_member_type`, `no_applicable_rule_version` | Find missing source evidence. Leave affected state unknown. |
| Uncertain inference | Warning | `unresolved_lifecycle_evidence`, `unsupported_transition`, `invalid_snapshot_field` | Review source meaning and the applicable rule. |
| Evidence conflict | Error | `same_day_state_contradiction`, `company_dependent_conflict`, `snapshot_state_conflict`, `invalid_correction` | Compare cited evidence and record a reviewed resolution. |
| Impossible transition | Error | `repeated_lifecycle_event`, `cyclic_correction` | Review event order and dates; use an audited correction if needed. |
| Balance difference | Error | `balance_difference` | Reconcile opening count, movements, and closing count. |

Every supported code has an explicit rule in `FINDING_RULES`. An unknown code
raises `ValueError` so a new producer cannot be silently misclassified. The
default severity describes review priority, not the truth of a state. A caller
may explicitly adjust severity without changing the finding ID or any
reconstruction. Review state is independent: `open`, `in_review`, `confirmed`,
or `resolved`.

The finding ID is a SHA-256 digest of its code, member subject key (or `None`
for an aggregate finding), scope, and sorted supporting and contradicting
ledger record IDs. Scope identifies a date, reporting period, or comparison.
Message text, input order, severity, review state, and recommended action are
excluded from identity. When evidence changes, the ID changes. The two evidence
roles and their source-row references remain visible. `order_findings()` sorts
by member, scope, code, and ID for repeatable output.

This is a reusable taxonomy for issue #26. Snapshot comparisons, reviewed
exceptions, and balance checks in later issues will supply their own findings
and cited evidence; this module does not infer those discrepancies itself.
