# Membership identifier map

This document contains aggregate, non-reversible identifier evidence only. It does not publish member IDs, company names, or other source values. Per-value keyed digests exist only during one profiling run and are not included in the returned results.

## Joining rules

Only comparisons listed in **Exact comparison evidence** are supported exact joins. Identifiers are compared exactly after trimming surrounding whitespace; leading zeroes are never removed for matching.

`Major Key` is parent/dependent evidence only when it exactly matches an `iMIS Id` in the same reviewed export. `Company ID` is not an automatic join key. Company names and unsupported keys are review-only.

In the membership-change export, `ChangeID` is the member's iMIS ID and
`Ordinal` identifies the individual change row for that member. Together they
form the candidate row key; matching change rows to members across sources
should still preserve source evidence and remain reviewable.

## Identifier profiling

A normalized collision is a group of two or more distinct numeric source values that would become equal if leading zeroes were removed. It is a warning, not a basis for a join.

### Current records

- Local input path: `data/processed/CSContactBasic_current.csv`
- Rows: 460835

| Identifier | Blank rows | Nonblank rows | Distinct values | Duplicate nonblank rows | Values with leading zeroes | Normalized collision groups | Values in collision groups |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `iMIS Id` | 0 | 460835 | 460835 | 0 | 16921 | 79 | 158 |
| `Major Key` | 263379 | 197456 | 32378 | 165078 | 24781 | 1 | 2 |
| `Company ID` | 295067 | 165768 | 27493 | 138275 | 19346 | 38 | 76 |

### CSContactBasic history

- Local input path: `data/processed/CSContactBasic_history.csv`
- Rows: 123801

| Identifier | Blank rows | Nonblank rows | Distinct values | Duplicate nonblank rows | Values with leading zeroes | Normalized collision groups | Values in collision groups |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `iMIS Id` | 0 | 123801 | 94431 | 29370 | 4167 | 6 | 12 |
| `Major Key` | 8224 | 115577 | 6323 | 109254 | 21192 | 0 | 0 |
| `Company ID` | 12009 | 111792 | 8948 | 102844 | 15844 | 4 | 8 |

### Membership changes

- Local input path: `data/raw/imisChanges3years_261014.csv`
- Rows: 1758

| Identifier | Blank rows | Nonblank rows | Distinct values | Duplicate nonblank rows | Values with leading zeroes | Normalized collision groups | Values in collision groups |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ChangeID` | 0 | 1758 | 1322 | 436 | 155 | 0 | 0 |
| `Ordinal` | 0 | 1758 | 1758 | 0 | 0 | 0 | 0 |

### Activity history

- Local input path: `data/raw/imis_Activity_historyDetail_202610.csv`
- Rows: 130223

| Identifier | Blank rows | Nonblank rows | Distinct values | Duplicate nonblank rows | Values with leading zeroes | Normalized collision groups | Values in collision groups |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `iMIS Id` | 0 | 130223 | 27781 | 102442 | 8581 | 0 | 0 |
| `Sequence` | 0 | 130223 | 130223 | 0 | 0 | 0 | 0 |

## Exact comparison evidence

Match rates use each side's distinct nonblank identifier count as its denominator. A rate of `—` means that side had no nonblank values.

| Relationship | Left distinct | Right distinct | Exact intersection | Left match rate | Right match rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Current records iMIS Id ↔ CSContactBasic history iMIS Id (exact member identifier) | 460835 | 94431 | 94431 | 20.5% | 100.0% |
| Current records iMIS Id ↔ activity history iMIS Id (exact member identifier) | 460835 | 27781 | 27778 | 6.0% | 100.0% |
| CSContactBasic history iMIS Id ↔ activity history iMIS Id (exact member identifier) | 94431 | 27781 | 14902 | 15.8% | 53.6% |
| Current records Major Key → current records iMIS Id (parent/dependent evidence) | 32378 | 460835 | 30125 | 93.0% | 6.5% |
| CSContactBasic history Major Key → CSContactBasic history iMIS Id (parent/dependent evidence) | 6323 | 94431 | 2528 | 40.0% | 2.7% |

## Retention boundary

Raw and processed exports remain ignored local operational files under `data/raw/` and `data/processed/`. Regenerate this committed aggregate document only from authorized local exports.
