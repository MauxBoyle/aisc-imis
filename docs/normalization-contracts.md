# Normalization contracts

`aisc_imis.normalization_contracts` is a small, dependency-free boundary
between source rows and later processing. It creates immutable Python
dataclasses from one source row at a time. It does **not** read files, provide a
CLI, join records, create an internal subject key, parse dates, infer event
meaning, or make membership-history decisions.

## Source evidence and provenance

Each accepted record contains a `SourceReference` with the caller-supplied
source name and row reference. It also contains `RawField` entries for every
column supplied by the caller. Column names, values, and field order are kept
verbatim. This lets a later reviewer see what the source actually contained.

The contract does not normalize unreviewed IDs into a common member or subject
identifier. For example, an `iMIS Id` remains source evidence, rather than a
claim that it matches a value in another source.

## Required and optional fields

Required fields must exist and contain non-whitespace text. Their accepted
values are retained exactly as provided; validation does not trim or recode
them. An optional mapped field is `None` when it is absent, empty, or only
whitespace. Other optional source columns remain available through raw fields.

| Record type | Required source fields | Optional mapped fields |
| --- | --- | --- |
| `CurrentRecord` | `iMIS Id`, `Member Type`, `Is Company`, `Is Member`, `Last Updated` | `Status` |
| `SnapshotObservation` | `iMIS Id`, `Member Type`, `Is Company`, `Is Member`, `Last Updated` | `Status` |
| `MembershipChange` | `ChangeID`, `Ordinal`, `Change Type`, `Member Type`, `ChangeUpdate`, `ChangeCreated`, `Status` | `ChangeEffective` |
| `ActivityRecord` | `iMIS Id`, `Sequence`, `A_Transaction`, `Activity Type`, `Effective Date`, `Member Type`, `Is a Company` | `Transaction Date` |

Use the corresponding `validate_*_record` function for one row, or a
`validate_*_records` function for a batch. Both take a source row and its
`SourceReference` explicitly.

## Rejections and input preservation

Invalid rows are never silently dropped. A single-row validator returns either
the record or a `ValidationRejection`. The rejection retains the original
reference, all raw fields, and a `ValidationFailure` for every missing or blank
required field. A batch returns `BatchValidationResult`, with separate
`accepted` and `rejected` tuples.

Rows are processed in supplied order. This layer intentionally does not sort,
deduplicate, reconcile, or select among duplicate or contradictory rows.
Those cases are evidence for a later, reviewed workflow—not validation errors
to be hidden here.

## Privacy boundary

The module is safe to use with authorized local source rows, but raw values can
include private information. Private exports in `data/raw/` and
`data/processed/` remain ignored. The fixture in `tests/fixtures/` uses only
invented values and exists solely to demonstrate contract behavior.

## Compatibility

These dataclasses are a public contract for downstream adapters and consumers.
Before changing field names, requiredness, accepted-value behavior, rejection
shape, or ordering policy, notify downstream adapter and consumer owners and
coordinate a compatible migration or versioned change.
