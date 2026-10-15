# aisc-imis

## Installation

Clone the repository and run `uv sync` to install dependencies.

## Usage

```bash
uv run aisc_imis
uv run --env-file .env aisc_imis
uv run python -m aisc_imis
```

## iMIS reference tables

Create or refresh the version-controlled iMIS reference tables from a local
company export:

```bash
uv run python scripts/generate_imis_reference.py data/raw/All_iMIS_Companies_261009.csv
```

The command writes CSV files to `data/reference/`. It preserves any member-type
and status meanings you have already replaced from `TBD`, while adding new codes
from the export with `TBD` meanings. The raw files in `data/raw/` are local input
data and are not committed.

## iMIS duplicate-company reports

Create review reports for likely duplicate company records:

```bash
uv run python scripts/find_imis_duplicates.py
uv run python scripts/find_imis_duplicates.py data/raw/All_iMIS_Companies_261009.csv --mode act
```

Each run creates a timestamped CSV and PDF in `data/processed/`. Use `--mode
all` (the default) to review every candidate, or `--mode act` to retain pairs
where either company has member type `ACT`. You can tune matching with
`--address-threshold` (default `90`) and `--name-threshold` (default `85`).

For speed and conservative matching, the command only compares companies that
share an extracted five-digit ZIP code; records without a ZIP are skipped.

> **Important exclusion:** The command deliberately excludes every company
> whose name contains `Test`, regardless of capitalization. This can exclude a
> genuine company, but is intended to keep known test accounts out of these
> reports. Review or remove this rule if it becomes a problem later.

Reports are review candidates, not instructions to merge records automatically.
Like `data/raw/`, `data/processed/` is local operational data and is not
committed.

## CSContactBasic snapshot merge

Combine all CSV files in `data/raw/` whose names contain `CSContactBasic`:

```bash
uv run python scripts/combine_contact_snapshots.py
```

The command writes `data/processed/CSContactBasic_combined_deduplicated.csv`.
If that output already exists, the command uses it as the historical base and
adds the matching files currently in `data/raw/`. This makes later incremental
updates repeatable; running the same update twice does not duplicate its rows.
It compares rows with the same `iMIS Id` and `Last Updated` value. Exact
duplicates are removed, and compatible rows are combined by filling blank
fields. If two populated fields disagree, both rows are retained. Rows without
a `Last Updated` value remain in a separate blank-date group. The obsolete
first-attempt export `Full_CSContactBasic_MB_1.csv` is excluded. The calculated
source fields `isMax`, `maxUpdate`, and `Table Names` are not copied to the result.

Split the combined file into one newest row per iMIS ID and all older rows:

```bash
uv run python scripts/split_contact_snapshots.py
```

This writes `data/processed/CSContactBasic_current.csv` and
`data/processed/CSContactBasic_history.csv`. If an ID has multiple rows tied at
its newest timestamp, the command stops instead of choosing one silently.

For Python code that needs to read the combined legacy evidence, use
`read_historical_snapshot_records(csv_path, reference_directory)`. It returns
immutable observations, rejections, and findings without changing the merge or
inferring membership transitions. The adapter reads the reviewed coverage
schedule in `data/reference/snapshot_dates.csv`: 2025-06-05, 2025-06-25,
2025-06-26, 2025-07-01, 2025-07-18, 2026-03-13, 2026-06-30, 2026-07-20, and
2026-10-14. A legacy row's derived `observation_date` is the first scheduled
date on or after its parsed `Last Updated`; its `observation_date_basis` marks
this as configured coverage. Neither date is proof of a membership transition.
Raw source fields, filename, and physical CSV row number remain attached to
each accepted observation. Keep CSV inputs and any adapter results local and
uncommitted because they may contain private data.

## Certified Domestic Fabricator reconciliation

Reconcile a Salesforce Certified Domestic Fabricator export against an iMIS
company export:

```bash
uv run python scripts/reconcile_certified_fabricators.py \
  data/raw/salesforce_certified_fabricators.csv \
  data/raw/All_iMIS_Companies_261009.csv
```

Both input paths are required. The Salesforce CSV must contain `Name`, the five
`Billing...` address fields, `Certification_ID__c`, `IMISID__c`, and
`InIMIS__c`. The report also includes
`Is_active_in_IMIS_for_Member_Discount__c` as `salesforce_active_for_member_discount`.
(API-style exports using `Id` and `Certified_Fabricator__c` are
also supported.) The iMIS CSV must contain `iMIS Id`, `Company`, `Full Address`,
`Member Type`, and `Status`. The command writes timestamped CSV and PDF files
to `data/processed/` (or `--output-dir`). Match thresholds default to `90` for
address and `50` for company name and can be changed with
`--address-threshold` and `--name-threshold`.

The report groups Salesforce records as `none`, `one`, or `many` matches and
writes one CSV row for every candidate pairing. It never filters by ZIP code:
different or missing ZIP codes can still match. This differs from the iMIS
duplicate-company report above, which requires matching five-digit ZIP codes
and skips records without them.

For exactly one candidate, the report checks the Salesforce iMIS ID and whether
the Salesforce `InIMIS__c` status agrees. A Salesforce `True` agrees only with iMIS
`Member Type` `ACT` and `Status` `A`; Salesforce `False` agrees with every
other iMIS type/status combination. Those verdicts are left unassessed for zero
or multiple candidates.

For address matching, `United States`, `USA`, and `US` are removed after
normalization so an otherwise identical address is not penalized when only one
source includes a country.

## Environment Variables

`.env.example` is the template; copy it to `.env` for development. `LOG_LEVEL` defaults to `INFO` (set it to `DEBUG` in `.env` for verbose console output). `LOG_FILE` defaults to `app.log` and controls the log-file path. `uv run --env-file .env` loads the development environment explicitly; it is not loaded automatically.

## Testing

```bash
uv run pytest
uv run pytest --cov
```

## Documentation

The aggregate-only [membership source inventory](docs/membership-source-inventory.md)
documents the schemas and observed coverage of the four membership inputs. To
refresh it from authorized local exports, run:

```bash
uv run python scripts/generate_membership_source_inventory.py
```

The generated Markdown intentionally contains no member rows or source cell
values. The raw and processed exports remain ignored local operational data.

The [normalization contracts](docs/normalization-contracts.md) describe the
immutable, source-row validation layer used before any matching or lifecycle
interpretation. Its fixtures contain invented values only; private source
exports in `data/raw/` and `data/processed/` remain ignored.

The same document also describes the reusable shared parsers for identifiers,
booleans, reviewed member-type/status codes, and dates. They retain the raw
source value beside a normalized value or structured finding. Slash-style
numeric dates follow a month/day/year default; adapters must explicitly opt in
to another policy and handle any ambiguity. Reviewed code meanings stay in the
version-controlled CSVs under `data/reference/`, not in parser business rules.

The [evidence ledger](docs/evidence-ledger.md) supplies immutable,
provenance-rich Python models for source-backed facts, candidate lifecycle
events, and snapshot-state observations. It keeps effective, recorded, and
observed dates separate; preserves conflicting records; and can round-trip the
models through one typed table format for local audit exports. Any generated
ledger exports belong in ignored `data/processed/`.

For an ordered view of evidence for already-confirmed member keys, use the
non-CLI member ledger service. This synthetic example preserves every record
and writes only to a caller-chosen local path:

```python
from aisc_imis.evidence_ledger import ObservedFact
from aisc_imis.member_ledger import (
    build_member_evidence_ledger,
    write_member_evidence_csv,
)
from aisc_imis.normalization_contracts import SourceReference

record = ObservedFact(
    subject_key="example-member-001",
    fact_name="membership_status",
    fact_value="active",
    source_reference=SourceReference("invented.csv", "row-1"),
)
ledger = build_member_evidence_ledger((record,))
member_records = ledger.records_for("example-member-001")
write_member_evidence_csv(ledger, "data/processed/member-evidence.csv")
```

The service treats `subject_key` as an identity already confirmed by its
caller. It does not match identifiers, choose a preferred source, remove
duplicates, or infer a lifecycle. Its CSV rows include a deterministic
SHA-256 content ID and remain local operational data.

To turn normalized adapter observations into those ledger records, use the
non-CLI functions in `aisc_imis.evidence_conversion`. They return immutable,
input-ordered records plus structured conversion findings; they do not export,
join identities, sort rows, or reconstruct a lifecycle. Normalized iMIS IDs
are the ledger `subject_key` for current, historical, and activity rows;
membership changes use `ChangeID`. Snapshot `Last Updated` is retained as a
recorded date and historical configured coverage is an observed date.
`ChangeEffective`/`ChangeCreated` and activity `Effective Date`/`Transaction
Date` remain distinct effective/recorded dates. Only reviewed mappings with a
lifecycle name create candidate events. Unresolved, unknown, or conflicting
codes stay as unresolved facts with findings. The reviewed `DUES` activity is
verified payment evidence only, never a membership transition.

For scripts or future interfaces that need the confirmed current-state export,
use the non-CLI `read_current_member_records` adapter with an explicit local CSV
path (normally `data/processed/CSContactBasic_current.csv`) and the reviewed
`data/reference/` directory. It returns immutable observations, structural row
rejections, and findings; it does not write files, deduplicate IDs, or infer
lifecycle transitions. The observations are present-state evidence, not dated
membership events. Inputs and any result or findings exports can contain private
data, so keep them local and uncommitted.

For a caller-supplied membership-change export, use the non-CLI
`read_membership_change_records(csv_path, reference_directory)` adapter. It
returns immutable observations, structural row rejections, and findings while
preserving every accepted row's raw fields, filename, and physical CSV row
number. In this export, `ChangeID` is the member's iMIS ID and `Ordinal`
identifies the individual change row for that member. Both remain text, and
the adapter reports duplicate `(ChangeID, Ordinal)` keys without dropping
either transaction. `ChangeEffective`, `ChangeCreated`, and
`ChangeUpdate` are parsed separately; no date is silently selected as a
lifecycle-event date and input rows are not sorted. The adapter checks only the
`Membership changes` / `Change Type` rows of the version-controlled
`data/reference/lifecycle-evidence-taxonomy.csv`. Missing, unresolved, or
conflicting mappings are findings—not inferred lifecycle facts—and the adapter
never joins a transaction to a member. Raw files in `data/raw/` and generated
results or findings reports remain ignored local operational data because they
can contain private information.

For a caller-supplied activity-history export, use the non-CLI
`read_activity_history_records(csv_path, reference_directory)` adapter. It
returns immutable observations, structural rejections, and findings while
retaining the canonical raw `ActivityRecord`, including action, source,
product, notes, other metadata, filename, and physical CSV row number. `iMIS
Id`, `Sequence`, and `A_Transaction` stay text, so leading zeroes remain
meaningful; duplicate `(iMIS Id, Sequence)` combinations are findings and no
rows are dropped. `Effective Date` and optional `Transaction Date` are parsed
as separate source evidence, even when they differ. The adapter reads only the
`Activity history` / `Activity Type` portion of the reviewed lifecycle
taxonomy and exposes a classification for review. Unknown, unresolved, and
conflicting mappings become findings. This includes payment classifications:
they remain payment evidence only and never create a membership transition or
status. Keep source CSVs, adapter results, and finding exports local and
uncommitted because they may contain private operational data.

## Cross-source ingestion findings report

Create one local review report from the current, historical,
membership-change, and activity-history adapters:

```bash
uv run python scripts/report_ingestion_findings.py \
  --current data/processed/CSContactBasic_current.csv \
  --history data/processed/CSContactBasic_history.csv \
  --membership-changes data/raw/membership_changes.csv \
  --activity-history data/raw/activity_history.csv
```

The command reads reviewed tables from `data/reference/` by default and writes
`ingestion-findings.json` and `ingestion-findings.md` to
`data/processed/ingestion-findings/`. Use `--reference-directory` or
`--output-directory` to choose local alternatives. The JSON report gives every
finding a deterministic SHA-256 ID, so identical input and reference data
produce the same IDs. Findings are review output, not a command failure:
structurally accepted rows continue to later processing even if they have a
bad parsed value, an unknown code, or a duplicate-key finding. Both reports
include raw source-row evidence and can contain private member information, so
they remain local and uncommitted.

## Membership date semantics

Create or refresh the aggregate-only date profiling report from authorized local
exports:

```bash
uv run python scripts/generate_membership_date_semantics.py
```

The generated [date-semantics report](docs/membership-date-semantics.md)
counts blanks, invalid values, date precision, explicit timezone markers, and
configured date-pair ordering without publishing member IDs or source date
values. It documents which date meanings remain open questions and keeps
effective dates, recorded/update dates, snapshot observation time, and report
cutoffs separate. Raw and processed exports remain ignored local operational
data.

The aggregate-only [member identifier map](docs/member-identifier-map.md)
records which identifiers have evidence for exact matching across the same four
membership inputs. Refresh it with:

```bash
uv run python scripts/generate_member_identifier_map.py
```

It reports counts, leading-zero behavior, and exact hashed intersections only.
It does not normalize IDs to create joins; `Company ID`, company names, and the
membership-change transaction key remain review-only unless the document says
otherwise.

## Membership lifecycle evidence taxonomy

Create or refresh the aggregate-only lifecycle evidence inventory and its
version-controlled reviewer matrix from the four authorized local exports:

```bash
uv run python scripts/generate_membership_lifecycle_taxonomy.py
```

The generated [lifecycle taxonomy](docs/membership-lifecycle-taxonomy.md)
describes state observations, lifecycle-event candidates, payment activity,
unknown activity codes, and metadata. Its companion
`data/reference/lifecycle-evidence-taxonomy.csv` preserves reviewer-provided
code meanings and countability notes when regenerated. Names, IDs, notes,
descriptions, payment values, and transaction identifiers are never published;
the transaction field is aggregate-only. The draft labels `joined`,
`reinstated`, `resigned`, `expelled`, `transferred`, `corrected`, and `other
observed` are possible inferences, not lifecycle rules. Payment evidence does
not automatically create a countable-status transition, and all unreviewed
meanings and countability effects remain `unknown` / `unresolved`.

## Versioned lifecycle rules

The reviewed [versioned lifecycle rules](docs/lifecycle-rules.md) provide a
small, pure Python service for deciding countability from explicitly supplied
observations and a reporting date. Its version-controlled configuration is
`data/reference/lifecycle-rules.csv`; the first provisional version applies on
and after 2026-10-15. It returns structured findings instead of guessing about
unknown, missing, or conflicting inputs. It does not read exports, join people,
or write reports, and `Status` remains outside membership decisions until that
policy is separately approved.

## Membership-history architecture

The privacy-safe [membership-history architecture baseline](docs/membership-history-architecture.md)
sets out the proposed evidence, reconstruction, and Board-adjustment model. It
keeps source observations, inferred operational history, and Board decisions
separate, and links unresolved lifecycle rules to their later implementation
issues. It contains no member-level source data.

```bash
uv run python scripts/serve_docs.py
uv run mkdocs build
```
