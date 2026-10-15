# Versioned lifecycle rules

`data/reference/lifecycle-rules.csv` is the reviewed, version-controlled
configuration for operational lifecycle countability. It is deliberately
separate from the evidence taxonomy: the taxonomy records what source evidence
exists, while this file records the limited decisions approved for reporting.

## First rule version

The first provisional version is `2026-10-15`, effective **on and after** that
reporting date. A request for an earlier date has no applicable rule version,
so the evaluator returns an `unknown` decision with a
`no_applicable_rule_version` finding. It never applies a later rule backwards.

The version counts `ACT`, `ASSOC`, `PROF`, `AFF`, `STU`, and `EDU`, plus the
approved branch/dependent variants listed in the rule file. Known Former and
Potential types are not countable. A company record with a dependent Member
Type, missing inputs, unknown codes, and unapproved state combinations are
`unknown` findings rather than inferred states.

The initial event mappings recognize joining, resignation, expulsion, and
reinstatement. Each event rule now has an explicit target state: joining and
reinstatement lead to `current_member`; resignation and expulsion lead to
`former_member`. `DUES` is payment evidence only (`evidence_only`) and has no
target state, so it does not make a member countable or create a transition.
`ChangeCreated` remains the default transition date. `ChangeEffective` is
retained as provenance pending a reviewed backdating exception.

`Status` is intentionally retained on the observation but not used for a
membership decision in this version. That makes the current reviewed policy
visible in code without silently treating `Status=A`, `Status=S`, or any other
status as approval.

## Python interface

```python
from datetime import date

from aisc_imis.lifecycle_rules import (
    LifecycleObservation,
    evaluate_countability,
    load_lifecycle_rules,
)

rules = load_lifecycle_rules("data/reference")
decision = evaluate_countability(
    LifecycleObservation(member_type="ACT", is_company=True, is_member=True),
    date(2026, 10, 15),
    rules,
)
assert decision.countability == "countable"
```

`load_lifecycle_rules(reference_directory)` validates and loads the CSV.
`evaluate_countability(observation, reporting_date, rules)` is pure: it does
not read source exports, identify people, join records, sort events, write
files, or make a report. Its immutable decision includes the selected rule
version, operational state, countability result, transition effect, event target
state, and zero
or more structured findings.

## Rule-table columns and review

Each row records its `rule_version`, inclusive `effective_reporting_date`,
state or event inputs, `allowed_transition`, `event_target_state`, countability outcome,
`precedence`, and `review_provenance`. `*` means that the input is not
constrained by that row; it is not a license to infer an unlisted Member Type.
Edit the CSV and tests together when approving a new version.

The remaining decisions are intentionally not encoded: Affiliate dues or
tonnage requirements; tonnage as evidence versus a condition; `Status=S`;
backdating exceptions; expulsion-batch timing; and unresolved `Major Key`
relationships. See the [lifecycle review checklist](lifecycle-review-todo.md).

## Privacy

The rule CSV contains only code-level policy and review provenance. Do not add
member names, IDs, raw source values, notes, or exports to it or to these docs.
Caller observations and decisions can contain operational data, so callers
must keep any local input/output files outside version control as described in
the project privacy guidance.
