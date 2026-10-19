# Lifecycle taxonomy review checklist

This checklist records business-rule questions that are not yet settled. It is
intended to support the membership-history roadmap; it is not an instruction to
change any source export or historical record.

The approved provisional decisions below are encoded from 2026-06-30 onward
in the version-controlled [lifecycle rules](lifecycle-rules.md). Decisions
that remain unchecked are deliberately findings, not inferred policy.

## Membership categories and countability

- [x] Count these categories in membership reporting: Full (`ACT`), Associate
  (`ASSOC`), Professional (`PROF`), Affiliate (`AFF`), Student (`STU`), and
  Educator (`EDU`).
- [x] Do not count Potential or Former member types as active members.
- [x] Provisionally treat `ACT`, `ASSOC`, `PROF`, `AFF`, `STU`, and `EDU` as
  reporting Member Types. This temporary assumption must be revisited at the
  earliest opportunity.
- [ ] Confirm whether Affiliates pay dues and/or tonnage, and whether this is
  evidence only or a required condition for active membership.
- [ ] Define the new Emerging Professional category once its iMIS encoding,
  countability, and dues/tonnage rules are known.

## Evidence and transition rules

- [x] Treat `DUES` as evidence of ongoing activity, not a membership
  transition.
- [x] `SubmittedTonnage_20261015.csv` is available locally. Its schema is
  company-level (`CoID`, tonnage amounts, submission date, quarter, and year);
  profile its keys, coverage, payment timing, and relationship to Full (`ACT`)
  members before using it in a rule.
- [ ] Decide whether Tonnage is supporting evidence only or required evidence
  for an Active Full member at a reporting cutoff.
- [x] Treat `RESIGNED`, `EXPULSION`, `REINSTATE`, and joining activity as
  lifecycle transitions.
- [x] Use `ChangeCreated` as the default transition date. Retain
  `ChangeEffective` in source provenance for later backdating review; do not
  silently use it as the event date.
- [ ] Ask whether legitimate backdating can make `ChangeEffective` differ from
  `ChangeCreated`, document permitted cases, and implement any approved
  exception in a later phase.
- [ ] Define the four annual expulsion batches: expected dates, approval
  authority, and how to handle a late or out-of-cycle expulsion.
- [ ] Confirm whether an absence of DUES should merely trigger review of a
  Former status, and define the allowed approval/process lag.
- [x] Temporarily ignore `Status` for membership decisions while displaying it
  in the provisional anomaly grids. Revisit this at the earliest opportunity.
- [ ] Confirm the meaning and historical treatment of `Status=S` (presumed
  Suspended), including whether a recent/current `S` is always a finding.
- [x] Retain contradictory evidence and send it to review. Implement reviewer
  decisions and their effects in a later project phase; do not choose a
  winning source automatically.

## Cross-field and group validation

- [x] Flag a company record (`Is Company=True`) whose Member Type ends in `D`;
  dependent codes represent people, not companies.
- [x] Treat `Major Key` as the expected link from a branch record to a
  non-branch record in the same group.
- [ ] Define the exact allowed combinations of Member Type, Status, Is Member,
  Is Company, and Member Status. These fields use different value sets, so the
  rule needs an allowed-combination table rather than literal equality.
- [ ] Decide how to classify a missing, unmatched, or branch-to-branch Major
  Key link.

## Source-quality follow-up

- [x] Do not use `ChangeUpdate` as a lifecycle date because the 2026-02-05
  concentration reflects a system-table update.
- [ ] Record the owner and source documentation for each approved lifecycle and
  countability rule so later reports can show their provenance.
