# Pending Board actions

Issue #32 defines a private, reviewable input for Board actions that may not yet
appear in iMIS. The loader validates records and reports possible duplicates. It
does not change source evidence or member state. Pass its validated result to
the [Board-adjusted membership view](board-adjusted-membership.md) to see
eligible adjustments beside operational counts.

Copy the empty version 1 template, `config/board_pending_actions.json`, to
`data/processed/board_pending_actions.json`. The `data/processed/` directory is
ignored by Git. Keep real member references, source document references, and
rationales there; never put them in tracked examples, tests, or documentation.

## JSON fields

The top-level object has exactly `version` (`1`) and `revisions` (an array).
Every revision is a complete snapshot of one action at one status. Append a new
revision to change a status or amend its details; keep earlier revisions intact.

| Field | Required | Meaning |
| --- | --- | --- |
| `action_id` | Yes | Stable ID shared by all revisions of one action. |
| `revision_id` | Yes | Unique ID for this revision across the file. |
| `prior_revision_id` | On later revisions | ID of the preceding revision of this action; omit on the first revision. |
| `member_ref` | Yes | Local member reference; it need not be an iMIS ID. |
| `action_kind` | Yes | `new-member-approval`, `expulsion`, or `correction`. |
| `status` | Yes | One of the five statuses below. |
| `status_date` | Yes | Date this status applies, in `YYYY-MM-DD` format. |
| `recorded_by` | Yes | Person who recorded this revision. |
| `rationale` | Yes | Reason for this revision. |
| `source_document_ref` | Yes | Traceable reference to the source document for this revision. |
| `imis_id` | No | Separate iMIS member ID, if known. |
| `effective_date` | No | Intended effective date, separate from `status_date`. |
| `imis_record_ref` | For `recorded-in-iMIS` | Reference to the iMIS record that now contains the action. |
| `member_type` | No; new-member approval only | Member Type approved by the Board, used for Board-adjusted counts and M2/M3 classification. Put it on the approved revision. |
| `desired_countable` | For a correction, one or more desired fields | Boolean desired member countability. |
| `desired_category` | For a correction, one or more desired fields | Desired Category string. |
| `desired_member_type` | For a correction, one or more desired fields | Desired Member Type string. |

A correction needs at least one desired field. Non-correction actions cannot use
desired fields. Only new-member approvals can use `member_type`. Optional fields
should be omitted when unknown, rather than set to `null`. Each later revision
must keep the action's `member_ref` and
`action_kind`, point to its immediate predecessor, and have a `status_date` no
earlier than that predecessor. Each action must have one initial revision; a
revision cannot branch from an older revision. The loader rejects unknown fields,
invalid dates, duplicate revision IDs, and broken chains with a field-specific
error.

## Status meanings

| Status | Meaning |
| --- | --- |
| `proposed` | Submitted for Board consideration. |
| `approved` | Board approved the action. |
| `rejected` | Board declined the action. |
| `withdrawn` | Proposal was withdrawn. |
| `recorded-in-iMIS` | The action has a referenced iMIS record. |

These are recorded states, not automatic instructions to alter operational
membership. The loader does not impose a transition sequence beyond a valid
revision chain. This preserves the actual record, including an amended proposal
or corrected status.

## Synthetic examples

This example uses invented identifiers and references. The second revision
preserves the first proposal and its source reference.

```json
{
  "version": 1,
  "revisions": [
    {
      "action_id": "example-approval-1",
      "revision_id": "example-revision-1",
      "member_ref": "invented-member-1",
      "action_kind": "new-member-approval",
      "status": "proposed",
      "status_date": "2026-10-01",
      "recorded_by": "Example Secretary",
      "rationale": "Listed in an invented Board packet.",
      "source_document_ref": "invented-packet/page-2"
    },
    {
      "action_id": "example-approval-1",
      "revision_id": "example-revision-2",
      "prior_revision_id": "example-revision-1",
      "member_ref": "invented-member-1",
      "action_kind": "new-member-approval",
      "status": "recorded-in-iMIS",
      "status_date": "2026-10-05",
      "recorded_by": "Example Secretary",
      "rationale": "The invented entry was located.",
      "source_document_ref": "invented-entry-log/row-1",
      "imis_id": "invented-imis-id-1",
      "imis_record_ref": "invented-imis-entry-1"
    },
    {
      "action_id": "example-correction-1",
      "revision_id": "example-revision-3",
      "member_ref": "invented-member-2",
      "action_kind": "correction",
      "status": "approved",
      "status_date": "2026-10-06",
      "recorded_by": "Example Secretary",
      "rationale": "Invented Board correction.",
      "source_document_ref": "invented-minutes/page-4",
      "desired_countable": false,
      "desired_category": "Invented Category"
    }
  ]
}
```

An expulsion uses `"action_kind": "expulsion"` and the same common fields. Its
`effective_date`, when known, is separate from the date of the proposal or
approval. Rejected and withdrawn actions remain in the revision history.

```python
from aisc_imis.board_pending_actions import load_board_pending_actions

result = load_board_pending_actions("data/processed/board_pending_actions.json")
for action in result.actions:
    print(action.action_id, action.current_revision.status)
for finding in result.possible_duplicates:
    print(finding.member_ref, finding.action_kind, finding.action_ids)
```

Distinct `action_id` values for the same `member_ref` and `action_kind` are
reported as possible duplicates. They stay separate, even if their statuses
differ. A reviewer must decide whether they represent separate Board actions or
an accidental duplicate; validation never merges them or chooses a winner.
