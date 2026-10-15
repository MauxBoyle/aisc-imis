# Normalization contracts

`aisc_imis.normalization_contracts` is a small, dependency-free boundary
between source rows and later processing. It creates immutable Python
dataclasses from one source row at a time. It does **not** read files, provide a
CLI, join records, create an internal subject key, infer event meaning, or make
membership-history decisions.

## Shared value parsers

`aisc_imis.normalization_parsers` provides equally small parsers for individual
source values. They are deliberately separate from the row contracts, so a
future adapter can choose its own source-column mapping. Each immutable
`ParseResult` has the unmodified `raw` value, a `normalized` value when parsing
succeeds, and zero or more `ParseFinding` values. Findings use the consistent
codes `blank`, `invalid`, and `ambiguous`; a parser never silently replaces a
bad value.

```python
from aisc_imis.normalization_parsers import parse_date, parse_identifier

parse_identifier("  000139  ")
# ParseResult(raw="  000139  ", normalized="000139", findings=())

parse_date("10/15/2026 1:05:23 PM")
# ParseResult(..., normalized=datetime(2026, 10, 15, 13, 5, 23), findings=())
```

Identifiers stay as text: only surrounding whitespace is removed, so leading
zeroes remain intact. Booleans accept the reviewed text values `True` and
`False` and produce Python `True` and `False` values. Blank or other text is
reported as a finding.

Member-type and status parsers trim a code and check it against an explicit,
caller-supplied codebook. Adapters should build those codebooks from the
reviewed `data/reference/member_types.csv` and `data/reference/statuses.csv`
tables. The parser treats codebook values as opaque: those tables are the place
for reviewed meanings, and the parser does not turn a code into a business or
lifecycle decision. `data/reference/boolean_values.csv` similarly documents
the accepted boolean text values.

Dates accept ISO dates, ISO timestamps, and the existing slash-style iMIS
dates/timestamps. An ISO timestamp with an offset or `Z` remains a timezone-
aware `datetime`; the parser does not assume or convert a timezone. Numeric
slash dates use **month/day/year** by default. A caller that enables both
`"mdy"` and `"dmy"` gets an `ambiguous` finding when one input could mean two
different dates, rather than a guess.

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

## Current-member CSV adapter

`aisc_imis.current_member_records` is the Python-facing adapter for a confirmed
current-state `CSContactBasic` export. It has no CLI and takes both the local
CSV path and the reviewed reference-table directory explicitly:

```python
from pathlib import Path

from aisc_imis.current_member_records import read_current_member_records

result = read_current_member_records(
    Path("data/processed/CSContactBasic_current.csv"),
    Path("data/reference"),
)
```

It reads CSV with UTF-8 BOM support and creates one immutable
`CurrentMemberObservation` for every row that has the five required source
values. Each observation retains its `CurrentRecord`, including every raw named
CSV field, the source filename, and physical CSV row number. It separately
normalizes the iMIS ID, member type, company/member flags, last-updated value,
and optional status. The `member_types.csv` and `statuses.csv` tables in the
given reference directory are required reviewed codebooks; unknown codes and
invalid values become `IngestionFinding` entries rather than silent changes.

Rows missing required values become `ValidationRejection` entries with their
raw evidence. If required headers are missing, the adapter returns a batch-level
finding and no partial row data. Blank `Status` is allowed and becomes `None`.
Duplicate normalized iMIS IDs produce a finding for every row in that duplicate
group, but all rows remain in input order.

The result deliberately does not deduplicate, reconcile, select a winning row,
write an output file, or infer a lifecycle event. These observations are
present-state evidence only: `Last Updated` is parsed source data, not a dated
membership transition.

## Historical snapshot CSV adapter

`aisc_imis.historical_snapshot_records` reads the combined legacy
`CSContactBasic` CSV while keeping it as historical evidence rather than a
membership-event ledger:

```python
from pathlib import Path

from aisc_imis.historical_snapshot_records import read_historical_snapshot_records

result = read_historical_snapshot_records(
    Path("data/processed/CSContactBasic_combined_deduplicated.csv"),
    Path("data/reference"),
)
```

Like the current-member adapter, it returns immutable observations, structural
row rejections, and `IngestionFinding` values. Every accepted observation keeps
its `SnapshotObservation` record (all raw named fields, CSV filename, and
physical row number), and separately exposes normalized identifiers, reviewed
codes, booleans, `Last Updated`, and optional status. Invalid values and unknown
codes produce findings without removing an otherwise structurally valid row.
If a data row contains more values than the header defines, those extra cells
are retained as raw fields named `__extra_csv_value_1`,
`__extra_csv_value_2`, and so on, alongside an incompatibility finding.

The version-controlled `data/reference/snapshot_dates.csv` schedule currently
lists coverage dates `2025-06-05`, `2025-06-25`, `2025-06-26`, `2025-07-01`,
`2025-07-18`, `2026-03-13`, `2026-06-30`, `2026-07-20`, and `2026-10-14`.
For a parsed legacy `Last Updated`, `observation_date` is the first configured
date on or after that date. `observation_date_basis` explicitly identifies that
derived value as configured coverage. It remains distinct from the parsed
source `last_updated`; neither is a verified membership-transition date. A row
outside the schedule (or with an unparseable update value) remains available
with `observation_date=None` and a `missing_observation_date` finding.

Repeated identical rows remain separate observations. Rows sharing normalized
iMIS ID and parsed `Last Updated` but disagreeing on normalized state fields
receive a finding for every involved row; the adapter does not choose between
them. Missing required headers and incompatible CSV shapes are also reported at
the input boundary. This adapter does not alter `combine_contact_snapshots`:
the combined export has no original per-row run-date field, so configured
coverage is deliberately not represented as source capture time.

## Membership-change CSV adapter

`aisc_imis.membership_change_records` is a reusable Python adapter for a
caller-selected membership-change CSV. It has no CLI:

```python
from pathlib import Path

from aisc_imis.membership_change_records import read_membership_change_records

result = read_membership_change_records(
    Path("data/raw/membership_changes.csv"),
    Path("data/reference"),
)
```

It returns immutable `MembershipChangeObservation` values, structural
`ValidationRejection` values, and `IngestionFinding` values. Each accepted row
keeps its `MembershipChange` contract with every raw named source field, source
filename, and physical CSV row number. `ChangeID` and `Ordinal` stay text, so
leading zeroes are not converted away. Duplicate `(ChangeID, Ordinal)` keys are
reported for every involved row; the rows remain separate and in CSV order.

The adapter checks member type and status against the reviewed codebooks in the
given reference directory. It reads
`lifecycle-evidence-taxonomy.csv` only for rows scoped to `Membership changes`
and `Change Type`. A missing mapping, a mapping whose draft lifecycle is
`unknown`, whose countability effect is `unresolved`, or conflicting mappings
creates a finding. Even a fully reviewed mapping is configuration for review,
not an inferred lifecycle transition: this adapter never joins a transaction to
a member or asserts that a member joined, resigned, or changed status.

`ChangeEffective`, `ChangeCreated`, and `ChangeUpdate` are parsed independently
and exposed as separate fields. The first is optional; invalid supplied dates
produce findings. The adapter does not sort these dates, assume one is the
event date, or reconcile an out-of-order transaction sequence. Notes, other
date columns, and code columns not explicitly parsed remain available through
the raw record provenance.

The taxonomy CSV is version-controlled review configuration. In contrast, raw
inputs under `data/raw/`, generated adapter results, and exported findings can
contain private operational data and remain ignored local files. Do not commit
them.

## Activity-history CSV adapter

`aisc_imis.activity_history_records` reads a caller-selected activity-history
CSV without turning activity into a membership-status decision:

```python
from pathlib import Path

from aisc_imis.activity_history_records import read_activity_history_records

result = read_activity_history_records(
    Path("data/raw/activity_history.csv"),
    Path("data/reference"),
)
```

The result contains immutable `ActivityHistoryObservation` values, structural
`ValidationRejection` values, and `IngestionFinding` values. An accepted
observation keeps its canonical `ActivityRecord`, including every raw named
CSV field, the source filename, and its physical CSV row number. This means
raw action, source, product, notes, and unreviewed metadata remain available
for later review. Extra cells beyond the CSV header are retained as
`__extra_csv_value_1`, `__extra_csv_value_2`, and so on, with a schema finding.

The required headers are `iMIS Id`, `Sequence`, `A_Transaction`, `Activity
Type`, `Effective Date`, `Member Type`, and `Is a Company`. `Transaction Date`
is optional. The iMIS ID, sequence, and transaction identifier remain text so
leading zeroes are preserved. Member type and company flag are normalized with
the reviewed member-type codebook and boolean parser; invalid values remain as
raw evidence and receive findings. Effective and transaction dates are parsed
and exposed separately. A difference between them is retained as distinct
evidence, not reconciled or treated as an error.

The adapter scopes `lifecycle-evidence-taxonomy.csv` to `Activity history` /
`Activity Type` and exposes a reviewed `ActivityClassification` separately on
each observation. Unknown, unresolved, and conflicting mappings receive
findings. Classification is review configuration only: payment activity stays
payment evidence, and no activity row creates a membership transition, state,
or status change. Duplicate normalized `(iMIS Id, Sequence)` combinations are
reported for every involved row, without dropping or reordering any rows.

Like the other adapters, this reader only accesses caller-selected local files
and writes no result. Raw inputs in `data/raw/`, generated results, and finding
exports may include private operational data; keep them local and uncommitted.

## Privacy boundary

The module is safe to use with authorized local source rows, but raw values can
include private information. Private exports in `data/raw/` and
`data/processed/` remain ignored. Do not commit a source export, an adapter
result, or an exported findings report. The fixture in `tests/fixtures/` uses
only invented values and exists solely to demonstrate contract behavior.

## Compatibility

These dataclasses are a public contract for downstream adapters and consumers.
Before changing field names, requiredness, accepted-value behavior, rejection
shape, or ordering policy, notify downstream adapter and consumer owners and
coordinate a compatible migration or versioned change.
