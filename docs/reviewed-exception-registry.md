# Reviewed exception registry

`aisc_imis.review_registry` records a reviewer's explanation beside a
reconciliation finding. It does not edit the finding, its `review_state`, its
evidence, comparison results, counts, or reconstructed membership state.

The tracked empty template at `config/review_registry.json` contains no member
data. Copy it to `data/processed/review_registry.json` for member-specific
reviews. That directory is ignored by Git. Keep real member keys and private
review notes there; do not add them to the tracked template or documentation.
Shared, tracked review entries should be limited to non-sensitive aggregate
findings, where `member_key` is `null`.

## Add a review

Find the current `ReconciliationFinding` and copy its `code`, `subject_key`,
`scope`, and `id` into `code`, `member_key`, `scope`, and `finding_id`. Then add
the reviewer, outcome, rationale, and review date. The two validity dates are
optional and inclusive. This example uses invented data:

```json
{
  "reviews": [
    {
      "code": "balance_difference",
      "member_key": "invented-member-1",
      "scope": "2026-10",
      "finding_id": "paste-the-current-finding-id-here",
      "reviewer": "Example Reviewer",
      "outcome": "explained",
      "rationale": "Invented source timing explains this difference.",
      "review_date": "2026-10-15",
      "valid_from": "2026-10-15",
      "valid_through": "2026-12-31"
    }
  ]
}
```

Only `accepted` and `explained` are valid outcomes. All dates use
`YYYY-MM-DD`. The registry rejects malformed dates, unknown outcomes, blank
required fields, extra fields, and duplicate `(member_key, code, scope)` keys.
Each review needs an explicit `member_key` (`null` for an aggregate finding).

```python
from datetime import date

from aisc_imis.review_registry import annotate_findings, load_review_registry

registry = load_review_registry("data/processed/review_registry.json")
result = annotate_findings(findings, registry, as_of=date(2026, 10, 15))
for annotation in result.findings:
    print(annotation.finding.id, annotation.status)
for review in result.unmatched_reviews:
    print("No current finding:", review.finding_id)
```

Pass the current findings from a reconciliation result as `findings`. An
unreviewed finding has status `unreviewed` and no attached review. A matching
review shows `accepted` or `explained` only within its validity period. Before
`valid_from` it is `inactive`; after `valid_through` it is `expired`. If the
finding's ID changes, it is `stale` even when a validity date also has passed.
The ID includes cited evidence, so a stale review needs another look at the
current evidence before the saved ID or rationale is updated. A change to the
member key, code, or scope leaves the saved review in `unmatched_reviews` and
the current finding unreviewed; check whether the review still applies before
creating a new entry. Expired entries also need a fresh review before extending
their validity. None of these statuses suppresses a finding.
