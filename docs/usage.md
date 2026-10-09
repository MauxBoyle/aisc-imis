# Usage

## Installation

Clone the repository and install dependencies:

```bash
uv sync
```

## Running

Via the CLI entrypoint:

```bash
uv run aisc_imis
uv run --env-file .env aisc_imis
```

Or as a Python module:

```bash
uv run python -m aisc_imis
```

## iMIS reference tables

Generate the reusable reference CSV files from a local iMIS company export:

```bash
uv run python scripts/generate_imis_reference.py data/raw/All_iMIS_Companies_261009.csv
```

By default, the command writes to `data/reference/`; use `--output-dir` to
choose a different destination. `member_types.csv` and `statuses.csv` begin
with `TBD` meanings. Replace those values as their meanings become known; later
generation preserves existing meanings and adds newly observed codes as `TBD`.

`data/raw/` is ignored because it holds local source exports. The generated
tables in `data/reference/` are committed so scripts and future interfaces can
use the same definitions.

## iMIS duplicate-company reports

Find likely duplicate companies and write one timestamped CSV and PDF report
per run:

```bash
uv run python scripts/find_imis_duplicates.py
uv run python scripts/find_imis_duplicates.py data/raw/All_iMIS_Companies_261009.csv --mode act
```

The first command uses the default input file
`data/raw/All_iMIS_Companies_261009.csv`, looks for all candidates, and writes
reports to `data/processed/`. The `act` mode keeps only pairs where either row
has `Member Type` equal to `ACT`.

Use `--output-dir` to choose a different report location. Matching defaults to
an address score of at least `90` and a company-name score of at least `85`;
change those with `--address-threshold` and `--name-threshold`.

The matcher compares only companies with the same extracted five-digit ZIP
code, so records without a ZIP (or with different ZIPs) are not compared. Treat
these reports as candidates for human review, never as automatic merge
instructions.

!!! warning "Intentional Test-account exclusion"

    Every company whose name contains `Test`, regardless of capitalization, is
    excluded before matching. This may omit a genuine company; the filter is an
    intentional choice to keep test accounts out of reports. Review or remove
    this rule if it becomes a problem later.

Both `data/raw/` and `data/processed/` are ignored local operational data
directories.

## Certified Domestic Fabricator reconciliation

Compare a Salesforce Certified Domestic Fabricator CSV with an iMIS company
CSV and write timestamped investigation reports:

```bash
uv run python scripts/reconcile_certified_fabricators.py \
  data/raw/salesforce_certified_fabricators.csv \
  data/raw/All_iMIS_Companies_261009.csv
```

Both paths are required. Salesforce input needs `Name`, `BillingStreet`,
`BillingCity`, `BillingState`, `BillingPostalCode`, `BillingCountry`,
`Certification_ID__c`, `IMISID__c`, and `InIMIS__c`. API-style exports using
`Id` and `Certified_Fabricator__c` are also supported. iMIS input needs `iMIS Id`,
`Company`, `Full Address`, `Member Type`, and `Status`.

The report column `salesforce_active_for_member_discount` comes from Salesforce
`Is_active_in_IMIS_for_Member_Discount__c`. `InIMIS__c` remains the source used
for the one-to-one membership-status comparison.

Reports go to `data/processed/` by default; use `--output-dir` to choose a
different folder. Address and name thresholds default to `90` and `50`, and
can be changed with `--address-threshold` and `--name-threshold`.

Every Salesforce record is reported. A blank company name or address cannot
produce a candidate. Results are grouped into `none`, `one`, and `many`; the
CSV has one row for each Salesforce/candidate pairing, or one blank-candidate
row for no match. The matcher does **not** filter by ZIP code, so records with
different ZIP codes—or no ZIP code—can match. In contrast, the iMIS
duplicate-company report requires matching five-digit ZIP codes and skips
records without one.

For exactly one candidate only, the report compares `IMISID__c` to `iMIS Id`
and checks the Salesforce `InIMIS__c` status. Salesforce `True` matches only iMIS `ACT` /
`A`; Salesforce `False` matches any other iMIS Member Type/Status combination.
These fields are unassessed for no-match and multiple-match groups.

Before fuzzy address comparison, the country variants `United States`, `USA`,
and `US` are removed. This prevents an otherwise identical address from losing
points when a country is present in only one source.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Console log level (DEBUG, INFO, …) |
| `LOG_FILE` | `app.log` | Path to the log file |

Copy `.env.example` to `.env` for development defaults, then run with `uv run --env-file .env`.
