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
without Member Type leaves the last supported type in place. Events do not
record Status, so the earlier Status remains the comparison baseline.
Status is compared as an observed field but does not decide membership under
the current rules. Countability is compared only when both the expected and
observed values can be evaluated with an applicable rule. Dates before
2026-10-15 have no rule-based countability conclusion.

Each immutable comparison returns `match`, `discrepancy`, or `unassessable`.
`unassessable` means independent evidence, a usable date, or a reviewed rule
is missing; it is not a verdict against the source row. A discrepancy is a
review cue, not a correction. Findings have stable IDs and cite the target
row plus the earlier snapshot or event source rows that support or contradict
it. A first observed row receives an `unknown_starting_state` finding. Same-day
contradictory rows receive `snapshot_state_conflict`, even when there is no
earlier history to compare with.

All input and output containing real member data must stay in local, ignored
storage. Tests and documentation use invented member data only.
