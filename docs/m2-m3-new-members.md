# M2 and M3 new members

`build_m2_m3_new_members(movements, iqa_rows, board_actions)` turns **counted quarterly joins** into two lists. An `ACT` join goes to M2; an `ASSOC` join goes to M3. Run `classify_quarterly_movements` with `join_measures={"ACT": "M2", "ASSOC": "M3"}` first. Reinstatements, rejected and withdrawn Board actions, and joins effective outside the period do not enter these lists. A Board approval can be counted before the membership update appears in iMIS. An operational iMIS join can be counted while Board approval is still proposed.

The classifier uses a half-open period `[start_date, end_date)` and an inclusive report cutoff. `effective_date` places the join in a quarter. `recorded_date` says when its operational evidence was entered or observed. `proposed_date` and `approved_date` describe Board revision dates when available. `report_cutoff` is the latest date considered for evidence. `operational_status` is `joined` when the row has lifecycle evidence and `pending-iMIS` for a Board-only join. `board_action_status` is the latest visible Board revision status; blank means no exact-ID Board action was found. A later `recorded-in-iMIS` status is a Board revision status, not another join.

## IQA display fields

`read_new_members_iqa(path)` reads the CsContact/FirmInfo export. It keeps IDs and Join Dates as text, trims surrounding whitespace, and stores the source path and CSV row number (header is row 1). Its column mapping is:

| IQA column | M2/M3 CSV column | Meaning |
| --- | --- | --- |
| `iMIS Id` | `imis_id` | Exact matching key; leading zeroes remain significant. |
| `Join Date` | `join_date` | IQA display value only; it does not select the quarter or approve a join. |
| `Member Type` | `member_type` | Checked against the classified type; classification supplies the CSV value. |
| `Company` | `company` | Display name. |
| `Full Address` | `full_address` | Display address. |
| `Category` | `category` | IQA display category. |
| `Tonnage Est` | `tonnage_est` | Estimated tonnage, kept as source text. |
| `Reference Contact` | `reference_contact` | Referral contact. |
| `Reference Company` | `reference_company` | Referral company. |

The nine IQA columns are required in the file header. Blank values produce `missing_iqa_field` findings. A classified join missing from the Join Date filtered extract remains in M2/M3 with blank display fields and a `missing_iqa_match` finding. Disagreeing rows for one exact iMIS ID produce `conflicting_iqa_matches`; display fields stay blank. Identical duplicate IQA rows produce `duplicate_iqa_match` and retain both source locations. An IQA Member Type that differs from the classified type produces `iqa_member_type_disagreement`. Multiple visible Board actions for one ID produce `conflicting_board_actions`; the row stays in the output without choosing one Board status. Findings need review before treating display fields as verified.

## Output and reconciliation

`write_m2_m3_csv(result, output_dir)` writes `m2_new_members.csv` and `m3_new_members.csv`, ordered by effective date and iMIS ID. Use ignored `reports/` for operational output. Each file has the same columns: `measure`, `imis_id`, `member_type`, `operational_status`, `board_action_status`, `proposed_date`, `approved_date`, `effective_date`, `recorded_date`, `report_cutoff`, `join_date`, `company`, `full_address`, `category`, `tonnage_est`, `reference_contact`, `reference_company`, `lifecycle_evidence_refs`, `board_evidence_ref`, and `iqa_source_refs`. Missing dates and display fields are blank. Evidence references point to ledger record IDs and source rows, Board action documents, and IQA file rows.

The result's `counts` gives the number of classified `ACT` and `ASSOC` joins. The builder checks that M2 and M3 row counts equal those classified counts, including rows with missing IQA details. The Q3 2026 sample in ignored `data/raw/NewMembersInQuarter32026.csv` contains 19 `ACT` and 22 `ASSOC` **IQA rows**; these are source counts, not classified join totals. A Q3 export needs reviewed Q3 lifecycle evidence and Board actions passed to the classifier before its M2/M3 counts can be verified.

```python
from aisc_imis.new_members import (
    build_m2_m3_new_members,
    read_new_members_iqa,
    write_m2_m3_csv,
)

# movements is a QuarterlyMovementResult classified with ACT/M2 and ASSOC/M3.
# board_actions is the same BoardPendingActions used for classification.
iqa_rows = read_new_members_iqa("data/raw/NewMembersInQuarter32026.csv")
result = build_m2_m3_new_members(movements, iqa_rows, board_actions)
print(result.counts, len(result.m2), len(result.m3))
for finding in result.findings:
    print(finding.code, finding.imis_id, finding.source_refs)
write_m2_m3_csv(result, "reports")
```
