# Evidence ledger

`aisc_imis.evidence_ledger` provides small immutable Python models for keeping
membership evidence reviewable before lifecycle reconstruction exists. It is a
library module, not a command-line tool, report generator, source adapter, or
set of lifecycle rules.

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
