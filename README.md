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
