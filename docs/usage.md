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

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Console log level (DEBUG, INFO, …) |
| `LOG_FILE` | `app.log` | Path to the log file |

Copy `.env.example` to `.env` for development defaults, then run with `uv run --env-file .env`.
