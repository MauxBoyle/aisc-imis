# Membership state reconciliation

`aisc_imis.member_state_reconciliation.reconcile_member_states` compares each
normalized historical and current row for an already-confirmed member with
independent evidence available at that row's comparison date. Callers supply a
`MemberEvidenceLedger`, historical `MembershipObservation` rows, current rows,
reviewed `LifecycleRules`, and an explicit `current_export_date`. The historical
rows use their configured `observation_date`. Current rows always use the
supplied export date, even if their source has a `Last Updated` value.

The module's `MembershipObservation.from_historical` and `from_current` helpers
accept rows returned by the corresponding CSV adapters. The input member key
must already be confirmed; this service does not resolve identifiers. The
ledger can hold supporting events and other reviewed evidence. The service
also turns each supplied observation into source-linked ledger entries for its
own comparisons.

For a target date, every snapshot on that same date is excluded from the
expected baseline. Earlier snapshots can support Member Type and Status. An
applicable, interpreted lifecycle event can update the expected Member Type
when it records one, and can support a countability transition. A later event
without Member Type leaves the last supported type in place. A newer snapshot
with a blank field also leaves that field's earlier value in place. Events do
not record Status, so the latest supported snapshot Status remains the
comparison baseline.
For countability, a Status-only snapshot leaves the last reviewed event or
rule-assessable snapshot in place. A newer snapshot containing some countability
fields but lacking a supported rule-based state makes countability unknown and
produces an `unassessable_countability_snapshot` finding.
Status is compared as an observed field but does not decide membership under
the current rules. A `match` requires known expected and observed Member Type,
Status, and countability. A missing observed Member Type or Status gets a
`missing_observed_state_field` finding. Unknown observed countability gets the
rule evaluator's finding, such as `missing_is_member` or
`no_applicable_rule_version`. Unknown expected countability also gets a
finding when earlier evidence exists. Dates before 2026-10-15 have no
rule-based countability conclusion and are unassessable.

Each immutable comparison returns `match`, `discrepancy`, or `unassessable`.
`unassessable` means at least one required comparison cannot be concluded;
it is not a verdict against the source row. A known difference still gets a
review finding, even if another field makes the overall comparison
unassessable. Findings have stable IDs and cite the target
row plus the earlier snapshot or event source rows that support or contradict
it. A first observed row receives an `unknown_starting_state` finding. Same-day
contradictory rows receive `snapshot_state_conflict`, even when there is no
earlier history to compare with.

All input and output containing real member data must stay in local, ignored
storage. Tests and documentation use invented member data only.
