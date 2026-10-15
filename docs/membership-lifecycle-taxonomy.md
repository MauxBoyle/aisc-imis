# Membership lifecycle evidence taxonomy

This aggregate-only discovery records what the four local exports can support. It does not establish lifecycle rules or operational counting rules.

## Evidence interpretation

- Direct facts are source-field observations, such as a populated status or payment field. They do not by themselves explain why a state exists.
- State observations describe a snapshot or recorded state; they are not proof of a transition.
- Possible inferences are unvalidated interpretations of event-candidate codes. They must be reviewed before use.
- Payment activity never automatically creates a countable-status transition. Every countability effect remains unresolved until a later rule is validated.
- `DUES` is confirmed direct payment evidence. It is retained for review, but never creates a lifecycle transition.

The unvalidated draft vocabulary is `joined`, `reinstated`, `resigned`, `expelled`, `transferred`, `corrected`, and `other observed`. These are possible inferences, not rules.

## Current records

- Local input path: `data/processed/CSContactBasic_current.csv`
- Rows: 460835

### Configured field inventory

| Field | Evidence class | Assertion level | Blank rows | Nonblank rows | Distinct values |
| --- | --- | --- | ---: | ---: | ---: |
| `Member Type` | state observation | direct fact | 0 | 460835 | 63 |
| `Member Status` | state observation | direct fact | 216254 | 244581 | 5 |
| `Status` | state observation | direct fact | 1988 | 458847 | 5 |
| `Category` | state observation | direct fact | 343643 | 117192 | 43 |
| `Is Member` | state observation | direct fact | 0 | 460835 | 2 |
| `Is Company` | state observation | direct fact | 0 | 460835 | 2 |

### Member type and status

Only nonblank configured code combinations are shown. Values are sorted by frequency and then alphabetically for repeatable output.

| Member Type | Status | Rows |
| --- | --- | ---: |
| NM | A | 153332 |
| FSTU | A | 99786 |
| PROFD | A | 45103 |
| FPROD | A | 28264 |
| STU | A | 27395 |
| ATT | A | 13227 |
| FPROF | A | 10964 |
| WEB | A | 9096 |
| ACTD | A | 9089 |
| NMC | A | 8472 |
| ATTM | A | 6797 |
| FACTD | A | 4525 |
| ARCD | A | 4324 |
| FAFFD | A | 4222 |
| PROF | A | 3642 |
| ASSCD | A | 3415 |
| FASCD | A | 2612 |
| PROFB | A | 2366 |
| FAFF | A | 1819 |
| IMP | A | 1804 |

106 lower-frequency combinations are omitted.

## CSContactBasic history

- Local input path: `data/processed/CSContactBasic_history.csv`
- Rows: 123801

### Configured field inventory

| Field | Evidence class | Assertion level | Blank rows | Nonblank rows | Distinct values |
| --- | --- | --- | ---: | ---: | ---: |
| `Member Type` | state observation | direct fact | 0 | 123801 | 56 |
| `Member Status` | state observation | direct fact | 33606 | 90195 | 4 |
| `Status` | state observation | direct fact | 78 | 123723 | 5 |
| `Category` | state observation | direct fact | 40290 | 83511 | 33 |
| `Is Member` | state observation | direct fact | 0 | 123801 | 2 |
| `Is Company` | state observation | direct fact | 0 | 123801 | 2 |

### Member type and status

Only nonblank configured code combinations are shown. Values are sorted by frequency and then alphabetically for repeatable output.

| Member Type | Status | Rows |
| --- | --- | ---: |
| PROFD | A | 56351 |
| STU | A | 24908 |
| ACTD | A | 11754 |
| FSTU | A | 6147 |
| NM | A | 5484 |
| FPROD | A | 4036 |
| ASSCD | A | 3612 |
| AFFD | A | 1659 |
| PROFB | A | 1569 |
| PROFB | NB | 1551 |
| PROF | A | 1057 |
| ATT | A | 824 |
| ACT | A | 710 |
| ACTB | A | 573 |
| ATTM | A | 573 |
| FPROF | A | 488 |
| EDU | A | 389 |
| ASSOC | A | 206 |
| FAFFD | A | 169 |
| PACTD | A | 157 |

57 lower-frequency combinations are omitted.

## Membership changes

- Local input path: `data/raw/imisChanges3years_261014.csv`
- Rows: 1758

### Configured field inventory

| Field | Evidence class | Assertion level | Blank rows | Nonblank rows | Distinct values |
| --- | --- | --- | ---: | ---: | ---: |
| `Change Type` | lifecycle-event candidate | possible inference | 3 | 1755 | 8 |
| `Member Type` | state observation | direct fact | 0 | 1758 | 16 |
| `Member Status` | state observation | direct fact | 0 | 1758 | 4 |
| `Status` | state observation | direct fact | 0 | 1758 | 4 |
| `Category` | state observation | direct fact | 30 | 1728 | 26 |
| `Is Company` | state observation | direct fact | 0 | 1758 | 2 |
| `Paid Through` | payment activity | direct fact | 663 | 1095 | 88 |

### Change type, member type, and status

Only nonblank configured code combinations are shown. Values are sorted by frequency and then alphabetically for repeatable output.

| Change Type | Member Type | Status | Rows |
| --- | --- | --- | ---: |
| EXPULSION | FASSC | A | 329 |
| EXPULSION | FACT | A | 208 |
| RESIGNED | FACT | A | 195 |
| SUSPENSION | ACT | A | 143 |
| RESIGNED | FASSC | A | 122 |
| SUSPENSION | FACT | A | 107 |
| EXPULSION | ACT | A | 81 |
| EXPULSION | ASSOC | A | 70 |
| Resigned | FASSC | A | 54 |
| SUSPENSION | FASSC | A | 47 |
| SUSPENSION | FASSC | S | 47 |
| REINSTATE | ACT | A | 39 |
| SUSPENSION | FACT | S | 33 |
| DROP | FASSC | A | 30 |
| REINSTATE | FACT | A | 26 |
| SUSPENSION | ASSOC | A | 24 |
| Resigned | FACT | A | 18 |
| REINSTATE | ASSOC | A | 16 |
| RESIGNED | ACT | A | 16 |
| EXPULSION | FACT | S | 15 |

44 lower-frequency combinations are omitted.

## Activity history

- Local input path: `data/raw/imis_Activity_historyDetail_202610.csv`
- Rows: 130223

### Configured field inventory

| Field | Evidence class | Assertion level | Blank rows | Nonblank rows | Distinct values |
| --- | --- | --- | ---: | ---: | ---: |
| `A_Transaction` | metadata | direct fact | 0 | 130223 | 31937 |
| `Activity Type` | unknown | possible inference | 0 | 130223 | 23 |
| `Member Type` | state observation | direct fact | 0 | 130223 | 51 |
| `ContactCategory` | unknown | possible inference | 18144 | 112079 | 34 |
| `ActivityCategory` | unknown | possible inference | 80822 | 49401 | 35 |
| `Action Codes` | unknown | possible inference | 73769 | 56454 | 484 |
| `Entity Code` | unknown | possible inference | 81734 | 48489 | 2 |
| `Other Code` | unknown | possible inference | 72110 | 58113 | 143 |
| `Product Code` | unknown | possible inference | 852 | 129371 | 588 |
| `Source Code` | unknown | possible inference | 56883 | 73340 | 730 |
| `Is a Company` | state observation | direct fact | 0 | 130223 | 2 |

### Activity type, category, and entity code

Only nonblank configured code combinations are shown. Values are sorted by frequency and then alphabetically for repeatable output.

| Activity Type | ActivityCategory | Entity Code | Rows |
| --- | --- | --- | ---: |
| DUES | PROF1 | AISC | 15749 |
| DUES | PROF2 | AISC | 9561 |
| DUES | FAB | AISC | 7589 |
| DUES | PROF3 | AISC | 4926 |
| DUES | DET1 | AISC | 2858 |
| DUES | PROF4 | AISC | 2372 |
| DUES | RETR | AISC | 1089 |
| DUES | DERC | AISC | 602 |
| DUES | PROF5 | AISC | 350 |
| DUES | EREC | AISC | 233 |
| DUES | DET10 | AISC | 206 |
| DUES | EQPM | AISC | 140 |
| DUES | SOFT | AISC | 132 |
| DUES | BEND | AISC | 101 |
| DUES | BOLT | AISC | 86 |
| DUES | IND | AISC | 79 |
| DUES | PROF6 | AISC | 66 |
| DUES | SVC | AISC | 58 |
| DUES | COTA | AISC | 53 |
| DUES | SUPP | AISC | 43 |

19 lower-frequency combinations are omitted.

## Privacy and retention boundary

Names, member IDs, company IDs, notes, descriptions, and transaction identifiers are never rendered. Transaction identifiers are reported only as aggregate cardinality. The committed matrix records approved lower-cardinality codes and reviewer decisions; raw exports remain local.
