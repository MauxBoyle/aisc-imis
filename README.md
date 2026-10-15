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

For scripts or future interfaces that need the confirmed current-state export,
use the non-CLI `read_current_member_records` adapter with an explicit local CSV
path (normally `data/processed/CSContactBasic_current.csv`) and the reviewed
`data/reference/` directory. It returns immutable observations, structural row
rejections, and findings; it does not write files, deduplicate IDs, or infer
lifecycle transitions. The observations are present-state evidence, not dated
membership events. Inputs and any result or findings exports can contain private
data, so keep them local and uncommitted.

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
