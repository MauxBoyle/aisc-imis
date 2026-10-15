# Membership source inventory

This version-controlled inventory contains schema and aggregate findings only. It does not retain or publish member rows, IDs, names, contact details, or other source cell values.

## Scope and limitations

The inventory reports observed file coverage, not business interpretations. The CSContactBasic history file contains older snapshot observations, but historical completeness cannot be assumed. Date anomalies are retained as findings; this process does not silently correct them.

Date plausibility rule: parsed dates before 1900 or after 2026-10-15 are flagged.

## Current records

- Source type: current-state export
- Local input path: `data/processed/CSContactBasic_current.csv`
- Extraction / derivation: Newest CSContactBasic row per iMIS Id, derived by scripts/split_contact_snapshots.py.
- Rows: 460835
- Headers (21): `City`, `Company`, `Full Name`, `iMIS Id`, `Member Type`, `State Province`, `Company ID`, `Company Member Type`, `Date Added`, `Email`, `Is Company`, `Is Member`, `Join Date`, `Major Key`, `Member Status`, `Status`, `Category`, `Last Updated`, `Full Address`, `Country`, `Website`

### Null findings

| Column | Blank rows |
| --- | ---: |
| `City` | 49617 |
| `Company` | 151013 |
| `Full Name` | 39438 |
| `iMIS Id` | 0 |
| `Member Type` | 0 |
| `State Province` | 74166 |
| `Company ID` | 295067 |
| `Company Member Type` | 276929 |
| `Date Added` | 2048 |
| `Email` | 54087 |
| `Is Company` | 0 |
| `Is Member` | 0 |
| `Join Date` | 198446 |
| `Major Key` | 263379 |
| `Member Status` | 216254 |
| `Status` | 1988 |
| `Category` | 343643 |
| `Last Updated` | 0 |
| `Full Address` | 47899 |
| `Country` | 50741 |
| `Website` | 456971 |

Most common blank-column patterns (up to five):

- 68180 rows: `Website`
- 61750 rows: `Company ID`, `Company Member Type`, `Join Date`, `Major Key`, `Member Status`, `Category`, `Website`
- 42829 rows: `Company ID`, `Company Member Type`, `Major Key`, `Category`, `Website`
- 38302 rows: `Company`, `Company ID`, `Company Member Type`, `Join Date`, `Major Key`, `Member Status`, `Category`, `Website`
- 28569 rows: `Category`, `Website`

### Candidate-key findings

- Candidate key: `iMIS Id`
- Complete key rows: 460835
- Distinct complete keys: 460835
- Duplicate complete-key rows: 0

### Date coverage

| Column | Nonblank | Parsed | Unparseable | Earliest | Latest | Implausible |
| --- | ---: | ---: | ---: | --- | --- | ---: |
| `Date Added` | 458787 | 458787 | 0 | 1998-01-09 | 2026-10-14 | 0 |
| `Join Date` | 262389 | 262389 | 0 | 1900-01-01 | 2720-02-01 | 9 |
| `Last Updated` | 460835 | 460835 | 0 | 1990-08-16 | 2026-10-14 | 0 |

## CSContactBasic history

- Source type: historical snapshot observations
- Local input path: `data/processed/CSContactBasic_history.csv`
- Extraction / derivation: Older CSContactBasic rows after the newest row per iMIS Id is separated by scripts/split_contact_snapshots.py; this is not assumed complete history.
- Rows: 123801
- Headers (21): `City`, `Company`, `Full Name`, `iMIS Id`, `Member Type`, `State Province`, `Company ID`, `Company Member Type`, `Date Added`, `Email`, `Is Company`, `Is Member`, `Join Date`, `Major Key`, `Member Status`, `Status`, `Category`, `Last Updated`, `Full Address`, `Country`, `Website`

### Null findings

| Column | Blank rows |
| --- | ---: |
| `City` | 2514 |
| `Company` | 28929 |
| `Full Name` | 7129 |
| `iMIS Id` | 0 |
| `Member Type` | 0 |
| `State Province` | 6144 |
| `Company ID` | 12009 |
| `Company Member Type` | 33431 |
| `Date Added` | 129 |
| `Email` | 7698 |
| `Is Company` | 0 |
| `Is Member` | 0 |
| `Join Date` | 33535 |
| `Major Key` | 8224 |
| `Member Status` | 33606 |
| `Status` | 78 |
| `Category` | 40290 |
| `Last Updated` | 0 |
| `Full Address` | 3664 |
| `Country` | 3618 |
| `Website` | 123075 |

Most common blank-column patterns (up to five):

- 67762 rows: `Website`
- 21521 rows: `Company`, `Company Member Type`, `Join Date`, `Member Status`, `Category`, `Website`
- 5298 rows: `Category`, `Website`
- 3026 rows: `State Province`, `Website`
- 2318 rows: `Company ID`, `Company Member Type`, `Join Date`, `Major Key`, `Member Status`, `Category`, `Website`

### Candidate-key findings

- Candidate key: `iMIS Id`, `Last Updated`
- Complete key rows: 123801
- Distinct complete keys: 123801
- Duplicate complete-key rows: 0

### Date coverage

| Column | Nonblank | Parsed | Unparseable | Earliest | Latest | Implausible |
| --- | ---: | ---: | ---: | --- | --- | ---: |
| `Date Added` | 123672 | 123672 | 0 | 1998-01-09 | 2026-06-30 | 0 |
| `Join Date` | 90266 | 90266 | 0 | 1900-01-01 | 2029-02-12 | 1 |
| `Last Updated` | 123801 | 123801 | 0 | 1998-01-15 | 2026-06-30 | 0 |

## Membership changes

- Source type: membership-change transaction history
- Local input path: `data/raw/imisChanges3years_261014.csv`
- Extraction / derivation: Local raw export named imisChanges3years_261014.csv; no additional row filtering is applied by the inventory.
- Rows: 1758
- Headers (20): `Change Type`, `Company`, `Member Type`, `ChangedBy`, `ChangeUpdate`, `ChangeCreated`, `ChangeEffective`, `ChangeID`, `Notes`, `Ordinal`, `Thru Date`, `Category`, `Is Company`, `ContactUpdateLast`, `Member Status`, `Member Status Date`, `Paid Through`, `Status`, `Updated By`, `ContactUpdated`

### Null findings

| Column | Blank rows |
| --- | ---: |
| `Change Type` | 3 |
| `Company` | 0 |
| `Member Type` | 0 |
| `ChangedBy` | 0 |
| `ChangeUpdate` | 0 |
| `ChangeCreated` | 0 |
| `ChangeEffective` | 377 |
| `ChangeID` | 0 |
| `Notes` | 453 |
| `Ordinal` | 0 |
| `Thru Date` | 1645 |
| `Category` | 30 |
| `Is Company` | 0 |
| `ContactUpdateLast` | 0 |
| `Member Status` | 0 |
| `Member Status Date` | 0 |
| `Paid Through` | 663 |
| `Status` | 0 |
| `Updated By` | 0 |
| `ContactUpdated` | 0 |

Most common blank-column patterns (up to five):

- 525 rows: `Thru Date`
- 392 rows: `Thru Date`, `Paid Through`
- 234 rows: `Notes`, `Thru Date`
- 228 rows: `ChangeEffective`, `Thru Date`
- 94 rows: `Notes`, `Thru Date`, `Paid Through`

### Candidate-key findings

- Candidate key: `ChangeID`, `Ordinal`
- Complete key rows: 1758
- Distinct complete keys: 1758
- Duplicate complete-key rows: 0

### Date coverage

| Column | Nonblank | Parsed | Unparseable | Earliest | Latest | Implausible |
| --- | ---: | ---: | ---: | --- | --- | ---: |
| `ChangeUpdate` | 1758 | 1758 | 0 | 2026-02-05 | 2026-10-02 | 0 |
| `ChangeCreated` | 1758 | 1758 | 0 | 2012-04-04 | 2026-10-02 | 0 |
| `ChangeEffective` | 1381 | 1381 | 0 | 2012-04-04 | 2027-05-04 | 1 |
| `Thru Date` | 113 | 113 | 0 | 1900-01-01 | 2026-06-03 | 0 |
| `ContactUpdateLast` | 1758 | 1758 | 0 | 2012-04-09 | 2026-10-12 | 0 |
| `Member Status Date` | 1758 | 1758 | 0 | 2009-11-25 | 2026-10-12 | 0 |
| `Paid Through` | 1095 | 1095 | 0 | 2012-03-31 | 2099-12-31 | 440 |
| `ContactUpdated` | 1758 | 1758 | 0 | 2012-04-09 | 2026-10-12 | 0 |

## Activity history

- Source type: activity transaction history
- Local input path: `data/raw/imis_Activity_historyDetail_202610.csv`
- Extraction / derivation: Local raw export named imis_Activity_historyDetail_202610.csv; no additional row filtering is applied by the inventory.
- Rows: 130223
- Headers (18): `iMIS Id`, `Sequence`, `A_Transaction`, `Activity Type`, `Effective Date`, `Transaction Date`, `Member Type`, `Company`, `ContactCategory`, `ActivityCategory`, `Action Codes`, `Entity Code`, `Note`, `Other Code`, `Product Code`, `Source Code`, `Description`, `Is a Company`

### Null findings

| Column | Blank rows |
| --- | ---: |
| `iMIS Id` | 0 |
| `Sequence` | 0 |
| `A_Transaction` | 0 |
| `Activity Type` | 0 |
| `Effective Date` | 0 |
| `Transaction Date` | 47 |
| `Member Type` | 0 |
| `Company` | 8896 |
| `ContactCategory` | 18144 |
| `ActivityCategory` | 80822 |
| `Action Codes` | 73769 |
| `Entity Code` | 81734 |
| `Note` | 129768 |
| `Other Code` | 72110 |
| `Product Code` | 852 |
| `Source Code` | 56883 |
| `Description` | 50561 |
| `Is a Company` | 0 |

Most common blank-column patterns (up to five):

- 46341 rows: `Note`
- 39635 rows: `ActivityCategory`, `Action Codes`, `Entity Code`, `Note`, `Other Code`, `Source Code`, `Description`
- 15281 rows: `ActivityCategory`, `Action Codes`, `Entity Code`, `Note`, `Other Code`
- 6758 rows: `ContactCategory`, `ActivityCategory`, `Action Codes`, `Entity Code`, `Note`, `Other Code`, `Source Code`, `Description`
- 4287 rows: `ActivityCategory`, `Entity Code`, `Note`, `Source Code`

### Candidate-key findings

- Candidate key: `iMIS Id`, `Sequence`
- Complete key rows: 130223
- Distinct complete keys: 130223
- Duplicate complete-key rows: 0

### Date coverage

| Column | Nonblank | Parsed | Unparseable | Earliest | Latest | Implausible |
| --- | ---: | ---: | ---: | --- | --- | ---: |
| `Effective Date` | 130223 | 130223 | 0 | 2020-05-07 | 3104-01-01 | 168 |
| `Transaction Date` | 130176 | 130176 | 0 | 1992-12-02 | 7202-05-04 | 21 |

## Retention boundary

The source exports remain local operational files under ignored `data/raw/` and `data/processed/` directories. This Markdown file is the committed source of truth for the aggregate inventory; regenerate it from authorized local exports when inputs change.
