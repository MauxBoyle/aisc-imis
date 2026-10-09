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

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Console log level (DEBUG, INFO, …) |
| `LOG_FILE` | `app.log` | Path to the log file |

Copy `.env.example` to `.env` for development defaults, then run with `uv run --env-file .env`.
