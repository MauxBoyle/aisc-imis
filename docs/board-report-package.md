# Board report package

Use `scripts/build_board_report_package.py` to create one local package for an M1–M5 reporting period. Supply every input path explicitly. Keep private exports and review records in ignored `data/raw/` or `data/processed/`, and place generated packages in ignored `reports/`.

## Prepare inputs

You need the four membership exports: current CSContactBasic, historical CSContactBasic, membership changes, and activity history. Use the same column formats described in the adapter and ingestion guides. Also prepare the new-member IQA CSV with `Join Date`, `Member Type`, `iMIS Id`, `Company`, `Full Address`, `Category`, `Tonnage Est`, `Reference Contact`, and `Reference Company`. Supply a Board actions JSON file using the version 1 `revisions` format and a review registry JSON file using the `reviews` format. The committed empty JSON files in `config/` are valid starting templates. Use the reviewed CSV tables in `data/reference/` unless you have a reviewed local replacement.

```bash
uv run python scripts/build_board_report_package.py \
  --period-start 2026-10-16 \
  --as-of-date 2026-12-31 \
  --board-cutoff 2027-01-15 \
  --current-export-date 2027-01-10 \
  --current-csv data/processed/CSContactBasic_current.csv \
  --history-csv data/processed/CSContactBasic_history.csv \
  --membership-changes-csv data/raw/membership_changes.csv \
  --activity-history-csv data/raw/activity_history.csv \
  --new-members-iqa-csv data/raw/new_members_iqa.csv \
  --board-actions-json config/board_pending_actions.json \
  --review-registry-json config/review_registry.json \
  --reference-directory data/reference \
  --output-directory reports/board-2026-q4
```

`--period-start` and `--as-of-date` are inclusive calendar dates. The program calculates the exclusive period end as the day after the as-of date. `--board-cutoff` is the last day of knowledge allowed for the Board view. `--current-export-date` is when the current file was exported; it must be no later than the cutoff. Current rows are dated at export time, even if their `Last Updated` values are older.

## Review the package

The seven measure files are `m1_membership_numbers.csv`, `m2_new_members.csv`, `m3_new_members.csv`, `m4_resignations.csv`, `m4_reinstatements.csv`, `m5_pending_proposals.csv`, and `m5_completed_expulsions.csv`. `member_drilldown.csv` shows one row per member with opening and closing countability and ledger record IDs. Look up those IDs in `member_evidence.csv` to trace source rows. `findings.csv` contains source, conversion, reconciliation, movement, M2–M5, and M1 status findings. A reviewed reconciliation finding remains in the file with its review status; stale, expired, and unmatched reviews remain visible too. Other findings retain their producer name and code.

Read `findings.csv` and M1 statuses before sharing a report. If a reconciliation finding has been investigated, add a review to your local review registry and run the same command again. A review annotates a finding; it does not change a count. Never use a balance difference as an adjustment. The `manifest.json` contains the dates, rule versions, SHA-256 fingerprints of source and reference files, fingerprints of generated files, and a deterministic run ID. Compare file hashes to verify a package or repeat a run with the same inputs and dates.

Historical source coverage is incomplete. A period before an applicable reviewed lifecycle rule, or one without enough dated evidence, can have unknown counts and findings. A current export cannot prove an earlier day's state. Keep the unknown result visible until reviewed evidence supports a conclusion.
