# Evidence ledger

`aisc_imis.evidence_ledger` provides small immutable Python models for keeping
membership evidence reviewable before lifecycle reconstruction. It is a library
module, not a command-line tool, report generator, source adapter, or set of
lifecycle rules.

The module reuses `SourceReference` from the normalization contracts. It does
not join subjects, choose the best source, assign numeric confidence, or remove
duplicate and contradictory records. If two sources disagree, retain both
records and let later review decide what they mean.

## Record models

| Model | Use | Provenance requirement |
| --- | --- | --- |
| `ObservedFact` | A value directly supported by one source row. | One `SourceReference` |
| `CandidateLifecycleEvent` | A possible event derived from one or more source rows. | One or more `SourceReference` values and a nonblank interpretation reason |
| `SnapshotStateObservation` | A state seen in one snapshot row, without claiming a transition. | One `SourceReference` |

Every model has separate optional `effective_date`, `recorded_date`, and
`observed_date` fields. A date says when a fact applies; a recorded date says
when the source stored it; an observed date says when a snapshot was seen or
extracted. None is silently substituted for another.

`InterpretationStatus` is a string enum with four distinct values:
`verified`, `inferred`, `ambiguous`, and `unresolved`. Status says how the
record's stated interpretation has been reviewed; it is not a confidence score.

All models use `@dataclass(frozen=True)`, so replacing a value requires making
a new record instead of silently changing existing evidence.

## Typed ledger-table contract

Use `to_tabular_rows(records)` to create one ordered table and
`from_tabular_rows(rows)` to restore the typed records. The functions return
tuples, preserving contradictory records and their input order.

Each table row has the following columns. Columns not used by a record type are
empty strings.

| Column | Meaning |
| --- | --- |
| `record_type` | Stable value: `observed_fact`, `candidate_lifecycle_event`, or `snapshot_state_observation` |
| `subject_key` | Caller-provided subject key; the ledger does not infer it |
| `fact_name`, `fact_value` | Fields used by `ObservedFact` |
| `event_name`, `interpretation_reason` | Fields used by `CandidateLifecycleEvent` |
| `state_name` | Field used by `SnapshotStateObservation` |
| `effective_date`, `recorded_date`, `observed_date` | Empty or ISO 8601 date/time values; timestamps keep their time precision |
| `interpretation_status` | One of the four status values |
| `source_references` | JSON array of source objects with `source_name` and `row_reference` |

`from_tabular_rows()` rejects malformed rows rather than guessing: unknown
record types or statuses, invalid ISO date/time values, invalid source JSON,
missing required fields, and the wrong number of source references all raise
`ValueError`.

Generated exports may be written locally under `data/processed/`, which is
ignored by Git because it can contain operational data. This module itself does
not write files.

## Member evidence ledger view

`aisc_imis.member_ledger` turns already-confirmed `subject_key` values into a
deterministic, member-focused view. Use
`build_member_evidence_ledger(records)` to create an immutable
`MemberEvidenceLedger`. Its `entries_for(subject_key)` method returns the
content IDs and records for one member; `records_for(subject_key)` returns the
typed records alone. An unknown key returns an empty tuple.

The caller is responsible for confirming a `subject_key` before building this
view. The module does not join identifiers, infer member identities, rank
sources, or reconstruct a membership lifecycle.

Every entry has a `record_id`: the SHA-256 hash of the record's canonical typed
table row. The ID is deterministic across repeated builds and input order.
Exact duplicate evidence has the same ID and is deliberately retained as a
separate row. Contradictory evidence is also retained.

Records are grouped by `subject_key`; groups are ordered by key. Within one
group, records sort by effective date, then recorded date, then observed date,
with missing values last for each role. Values are compared as their canonical
ISO 8601 source values. In particular, the view neither converts timezones nor
treats a date-only value as midnight. Remaining ties use `record_id`.

`write_member_evidence_csv(ledger, output_path)` writes a CSV only to the
explicit path provided by the caller and creates its parent directories when
needed. It writes `record_id` followed by the typed-ledger columns in a fixed
order. Use a local ignored path such as `data/processed/member-evidence.csv`;
do not commit operational exports.

## Converting normalized iMIS observations

`aisc_imis.evidence_conversion` is the small, non-CLI bridge from the four
normalized source adapters to these ledger models. Its conversion functions
return an `EvidenceConversionResult` with ordered immutable `records` and
structured `findings`. They do not write an export, sort rows, join identities,
or reconstruct a lifecycle.

Current and historical snapshot observations emit one `SnapshotStateObservation`
for every present normalized `member_type`, `status`, `is_member`, and
`is_company` value. The state name is written as `field=value`, in adapter
field order. The normalized iMIS ID is the `subject_key`; `Last Updated` is the
`recorded_date`; historical rows also retain their configured coverage date as
`observed_date`.

Membership-change records use `ChangeID` as their `subject_key`; despite its
name, this field is the member's iMIS ID. A reviewed taxonomy mapping with a
lifecycle name becomes an inferred `CandidateLifecycleEvent`, with
`ChangeCreated` as both the default event date (`effective_date`) and recorded
date. `ChangeEffective` remains available in the immutable source-row
provenance for a later backdating review; it is not silently used as the event
date. Activity-history records use the normalized iMIS ID, `Effective Date`,
and `Transaction Date` in the same roles. Unknown, conflicting, and unresolved
mappings are retained as unresolved `ObservedFact` records and get conversion
findings; they never become transitions.

The reviewed `DUES` activity mapping is a special safeguard: it becomes a
verified `payment_activity` fact, not a lifecycle event. Payment evidence can
be useful in review, but it does not prove a membership transition.

## Lifecycle reconstruction

`aisc_imis.lifecycle_reconstruction` reconstructs the state of one already
confirmed member from `MemberLedgerEntry` values. It is pure: it does not read
exports, match identities, write files, or choose a preferred contradictory
source. Callers pass the entries for one `subject_key`, an as-of date, and the
reviewed lifecycle rules.

The result contains a current `state`, inclusive-start/exclusive-end
`StateInterval` values, the supporting ledger entries, and structured findings.
Before the first usable evidence its opening strategy is explicitly
`UNKNOWN_BEFORE_COVERAGE`; no later snapshot is backfilled into earlier time.
Snapshot fields from the same source row and dates are grouped into one rule
observation, and a known snapshot state carries forward until later
unambiguous evidence. Evidence must both apply by the requested date and have
been recorded or observed by that date. Missing dates, unresolved evidence,
unavailable rule versions, and same-day conflicting states result in `unknown`
rather than a guess. Conflicting same-day evidence stays in the result with a
`same_day_state_contradiction` finding.
