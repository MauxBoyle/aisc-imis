# Membership-history architecture baseline

This is a proposed, privacy-safe design baseline for reconstructing membership
history from the evidence inventoried in issues #8–#11. It is not a member
export, a finalized data schema, or a statement of business rules. In
particular, it does not decide which transitions are countable.

The design preserves what sources said, what the reconstruction inferred, and
what a Board later chose to adjust as separate things. This makes a result
reviewable without publishing member-level data in repository documentation.

## Evidence and provenance

Every normalized record must retain provenance sufficient to answer: *what did
the source say, when was it recorded or observed, and why was this conclusion
made?* The evidence layer distinguishes:

- **Observed evidence**: a source-supported value or row, such as a status in a
  dated snapshot. It is not automatically a lifecycle event.
- **Candidate event**: source activity that may suggest a transition, but whose
  meaning, timing, or countability has not yet been reviewed.
- **Inferred history**: a derived conclusion made from one or more observations
  and reviewed rules. It must link to those inputs and the rule version.

Dates must keep their meaning. An effective date supports when a fact applies;
a recorded date says when a source stored it; an observation date says when a
snapshot was seen or extracted. None substitutes for another when missing.

## Proposed normalized record shapes

These are logical shapes, not a committed database schema. Fields may be added
after later issues validate the source mappings.

| Shape | Purpose | Minimum fields |
| --- | --- | --- |
| Normalized record | Common container for one source-derived fact | stable internal subject key, source name, source row/reference key, field/value, effective date, recorded date, observation date, evidence ID |
| Provenance/evidence | Links a fact to its source and transformation | evidence ID, source/version, local location, extraction time, content fingerprint, mapping/rule version, confidence or review state |
| Candidate event | Represents unconfirmed event-like activity | candidate ID, subject key, event label/code, possible effective date, evidence IDs, interpretation status |
| Snapshot observation | Represents a state seen at a point in time | observation ID, subject key, observed status/type, observation date, source-supported effective date if any, evidence ID |
| Inferred history | Explains a conclusion derived from evidence | inference ID, subject key, conclusion, supporting and contradicting evidence IDs, rule version, reviewer state |
| State interval | Represents a reconstructed operational state over time | interval ID, subject key, operational state, start/end boundaries, boundary basis, inference IDs, uncertainty flag |
| Finding | Captures conflicts, gaps, or reviewer work | finding ID, subject key, category, severity, evidence IDs, disposition, reviewer notes |
| Board adjustment | A separately authorized overlay to a result | adjustment ID, subject key, requested adjustment, scope, rationale reference, authorizer, effective range, created/reversed timestamps |

The internal subject key should be based only on a reviewed identifier mapping.
Unverified identifiers, names, company IDs, and transaction keys remain
evidence for review rather than automatic joins.

## Status at a date

To answer “what was the status on date *D*?”, first prefer source-supported
effective dates. Build state intervals from reviewed transitions and snapshot
observations, then select the interval containing *D*. Preserve the recorded
date and observation date with the evidence even when an effective date is
available.

If the evidence only shows a status at an observation date, the system may say
that the state was **observed on** that date. It must not backdate the state to
an earlier date unless a reviewed rule and supporting evidence permit it.
When the result is unresolved, return an uncertainty or finding instead of
inventing a status.

## Opening state and incomplete history

Coverage begins with the earliest usable evidence for a subject, not with an
assumed membership start. The reconstruction must distinguish:

- **unknown before coverage**: no reliable conclusion can be made before the
  first usable evidence;
- a **snapshot observation**: a state directly observed at coverage start; and
- an **inferred starting state**: a bounded conclusion drawn from reviewed
  evidence, labeled as inferred and linked to its rationale.

An opening observation can start a state interval at its observation date, but
does not prove the start date of membership or the prior state. This conservative
policy remains in effect until later lifecycle-rule work validates an exception.

## Operational reconstruction and Board adjustments

The operational reconstruction is immutable for a given source set and rule
version: rerunning it creates the same observed evidence, inferred history,
state intervals, and findings. Corrections to source mappings or rules create a
new version; they never silently rewrite a prior result.

A Board adjustment is not an operational fact. It is a reversible overlay,
separate from operational facts, that references a particular operational
result and records its
authorization, rationale, scope, and effective range. Queries may show either
the operational state or the Board-adjusted state, clearly labeled. Removing or
reversing an adjustment restores the underlying operational reconstruction.

## Data ownership and privacy

Raw inputs remain local, unchanged, and ignored by version control. They are
the authoritative evidence for discovery, not repository artifacts. Reusable
parsing, matching, validation, and reconstruction logic belongs in `src/`.
Reviewed mappings and rules belong in version-controlled reference files with a
review history. Generated reports and operational outputs remain ignored.

Repository documentation and tests may use synthetic examples and aggregate
counts only. They must not include member names, member IDs, addresses, notes,
transaction identifiers, source-cell values, or raw/processed exports.

## Open decisions, risks, and downstream issues

The following items are deliberately unresolved. Each must be reviewed with
supporting evidence before implementation begins; its discovery result must be
recorded in the [parent tracker (#7)](https://github.com/MauxBoyle/aisc-imis/issues/7)
and the affected future issues must be notified.

| Open decision or risk | Questions to resolve | Affected later issues |
| --- | --- | --- |
| Countability | Which operational states and transitions count, for which report and period? | #13, #14, #15 |
| Approval timing | Does approval, entry, payment, or another date make a transition effective? | #16, #17, #18 |
| Expulsions and resignations | Which evidence distinguishes them, and can either be reversed or corrected? | #19, #20, #21 |
| Transfers | Does a transfer preserve membership, end one record, or create linked intervals? | #22, #23 |
| Corrections | How should source corrections supersede a prior operational conclusion while retaining auditability? | #24, #25 |
| Duplicate or conflicting evidence | When may records be joined, and how are disagreements surfaced rather than selected silently? | #26, #27, #28 |
| Date cutoffs | Which reporting cutoff, timezone, and inclusive/exclusive boundary apply to each question? | #29, #30, #31 |
| Incomplete history | What evidence is enough to infer an opening state or interval before observation coverage? | #32, #33, #34 |
| Snapshot and event reconciliation | How do snapshot observations interact with candidate events and missing source-supported dates? | #35, #36 |
| Board adjustment governance | Who may authorize, review, publish, reverse, and audit an overlay? | #37, #38 |
| Release and review controls | What validation, privacy checks, and notification are required before results are used? | #39 |

### Discovery-change governance

When new discovery changes an assumption, attach or reference the supporting
evidence, update the parent tracker (#7), identify every affected future issue,
and notify those issues before their implementation work begins. Until that
review occurs, preserve the prior result and label the changed conclusion as a
finding or unreviewed candidate rather than a new rule.

## Next implementation boundary

Later work may implement readers, validators, rule versions, and reconstruction
only after the applicable decisions above are reviewed. This baseline permits
safe experimentation with synthetic data and aggregate-only documentation; it
does not authorize publishing operational membership history.
