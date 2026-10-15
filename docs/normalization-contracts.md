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
