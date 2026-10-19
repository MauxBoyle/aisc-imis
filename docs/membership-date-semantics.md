# Membership date semantics

This report contains aggregate evidence only. It never retains or publishes member IDs, names, or source date values.

## Scope and guardrails

Field names alone do not prove business meaning. The classifications below are working descriptions or explicit open questions, not data-model facts.

Date-only values remain dates: this discovery does not invent a time of day. Timezone-free timestamps remain timezone-free; no timezone is assumed or converted. The explicit-timezone count reports only source values that carry an offset or `Z` marker.

Configured pair tables provide aggregate evidence of missing pairs and left-after-right (out-of-order) pairs; they do not establish business meaning.

This run observed 591668 timestamp values, including 0 with an explicit timezone marker.

Dates before 1900 or after 2026-10-15 are counted as implausible.

## Current records

- Local input path: `data/processed/CSContactBasic_current.csv`
- Rows: 460835

### Field meanings to validate

| Field | Classification / open question |
| --- | --- |
| `Date Added` | Recorded/create-date candidate. It may be a contact-record creation date rather than a membership date. |
| `Join Date` | First-join effective date candidate when countable company evidence supports it; conflicting dates require review. |
| `Last Updated` | Recorded/update-date candidate. It records an update observation, not necessarily an effective change. |

### Field profile

| Field | Blank | Parseable | Invalid | Date-only | Timestamp | Explicit timezone | Implausible |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `Date Added` | 2048 | 458787 | 0 | 458787 | 0 | 0 | 0 |
| `Join Date` | 198446 | 262389 | 0 | 262389 | 0 | 0 | 9 |
| `Last Updated` | 0 | 460835 | 0 | 0 | 460835 | 0 | 0 |

### Configured pair ordering

The left field is compared with the right field at date precision. A missing pair has at least one blank value; an invalid pair has no blanks but at least one unparseable value.

| Pair | Earlier (left < right) | Same | Later (left > right) | Missing pair | Invalid pair |
| --- | ---: | ---: | ---: | ---: | ---: |
| Join Date compared with Date Added | 18797 | 185686 | 57891 | 198461 | 0 |

## CSContactBasic history

- Local input path: `data/processed/CSContactBasic_history.csv`
- Rows: 123801

### Field meanings to validate

| Field | Classification / open question |
| --- | --- |
| `Date Added` | Recorded/create-date candidate. It may be a contact-record creation date rather than a membership date. |
| `Join Date` | First-join effective date candidate when countable company evidence supports it; conflicting dates require review. |
| `Last Updated` | Recorded/update-date candidate. It records an update observation, not necessarily an effective change. |

### Field profile

| Field | Blank | Parseable | Invalid | Date-only | Timestamp | Explicit timezone | Implausible |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `Date Added` | 129 | 123672 | 0 | 123672 | 0 | 0 | 0 |
| `Join Date` | 33535 | 90266 | 0 | 90266 | 0 | 0 | 1 |
| `Last Updated` | 0 | 123801 | 0 | 0 | 123801 | 0 | 0 |

### Configured pair ordering

The left field is compared with the right field at date precision. A missing pair has at least one blank value; an invalid pair has no blanks but at least one unparseable value.

| Pair | Earlier (left < right) | Same | Later (left > right) | Missing pair | Invalid pair |
| --- | ---: | ---: | ---: | ---: | ---: |
| Join Date compared with Date Added | 10996 | 43919 | 35296 | 33590 | 0 |

## Membership changes

- Local input path: `data/raw/imisChanges3years_261014.csv`
- Rows: 1758

### Field meanings to validate

| Field | Classification / open question |
| --- | --- |
| `ChangeUpdate` | Recorded/update-date candidate. It may be transaction maintenance timing, not effective timing. |
| `ChangeCreated` | Recorded/create-date candidate. Its relation to transaction entry and business effect needs validation. |
| `ChangeEffective` | Candidate effective date. Validate the covered event and backdating rules before effective ordering. |
| `Thru Date` | Open question: through/end date. It may represent entitlement, billing, or another interval boundary. |
| `ContactUpdateLast` | Contact update-date candidate. Do not treat a contact update as membership timing without validation. |
| `Member Status Date` | Candidate membership-status effective date. Confirm which status change it records and whether it is backdated. |
| `Paid Through` | Open question: payment/through date. It is not assumed to be an effective membership date. |
| `ContactUpdated` | Contact update-date candidate. Do not conflate contact maintenance with membership events. |

### Field profile

| Field | Blank | Parseable | Invalid | Date-only | Timestamp | Explicit timezone | Implausible |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ChangeUpdate` | 0 | 1758 | 0 | 0 | 1758 | 0 | 0 |
| `ChangeCreated` | 0 | 1758 | 0 | 0 | 1758 | 0 | 0 |
| `ChangeEffective` | 377 | 1381 | 0 | 1381 | 0 | 0 | 1 |
| `Thru Date` | 1645 | 113 | 0 | 113 | 0 | 0 | 0 |
| `ContactUpdateLast` | 0 | 1758 | 0 | 0 | 1758 | 0 | 0 |
| `Member Status Date` | 0 | 1758 | 0 | 1758 | 0 | 0 | 0 |
| `Paid Through` | 663 | 1095 | 0 | 1095 | 0 | 0 | 440 |
| `ContactUpdated` | 0 | 1758 | 0 | 0 | 1758 | 0 | 0 |

### Configured pair ordering

The left field is compared with the right field at date precision. A missing pair has at least one blank value; an invalid pair has no blanks but at least one unparseable value.

| Pair | Earlier (left < right) | Same | Later (left > right) | Missing pair | Invalid pair |
| --- | ---: | ---: | ---: | ---: | ---: |
| ChangeEffective compared with ChangeCreated | 146 | 1230 | 5 | 377 | 0 |
| ChangeEffective compared with ChangeUpdate | 1273 | 107 | 1 | 377 | 0 |
| Member Status Date compared with ChangeEffective | 204 | 440 | 737 | 377 | 0 |

## Activity history

- Local input path: `data/raw/imis_Activity_historyDetail_202610.csv`
- Rows: 130223

### Field meanings to validate

| Field | Classification / open question |
| --- | --- |
| `Effective Date` | Candidate effective date. Validate the activity type and business effect before using it for ordering. |
| `Transaction Date` | Recorded/transaction-date candidate. Preserve it as provenance rather than assuming it is effective timing. |

### Field profile

| Field | Blank | Parseable | Invalid | Date-only | Timestamp | Explicit timezone | Implausible |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `Effective Date` | 0 | 130223 | 0 | 130223 | 0 | 0 | 168 |
| `Transaction Date` | 47 | 130176 | 0 | 130176 | 0 | 0 | 21 |

### Configured pair ordering

The left field is compared with the right field at date precision. A missing pair has at least one blank value; an invalid pair has no blanks but at least one unparseable value.

| Pair | Earlier (left < right) | Same | Later (left > right) | Missing pair | Invalid pair |
| --- | ---: | ---: | ---: | ---: | ---: |
| Effective Date compared with Transaction Date | 56883 | 18890 | 54403 | 47 | 0 |

## Recommended date roles

Use a validated, source-supported effective date only to order effective events. Preserve recorded, created, transaction, and update dates as separate provenance. Supply snapshot observation time and reporting cutoff as independent report inputs; neither is a substitute for a source date.

## Unresolved meanings

- Contact dates and membership dates may describe different entities and must not be treated as interchangeable without validation.
- Payment and through dates may represent entitlement, billing, or another business rule; their effective-date meaning remains open.
- The reviewed exports do not provide a per-row snapshot-capture timestamp. A file-level observation time, if known, must be supplied separately.

## Retention boundary

The CSV exports remain ignored local operational data in `data/raw/` and `data/processed/`. This committed document contains only aggregate evidence and should be regenerated from authorized local exports when inputs change.
