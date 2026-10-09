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

```bash
uv run python scripts/serve_docs.py
uv run mkdocs build
```
