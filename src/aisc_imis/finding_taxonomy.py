"""Stable, evidence-linked findings for lifecycle reconciliation.

This module describes reviewer work. It never changes a lifecycle decision or
selects which conflicting source is correct.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from aisc_imis.evidence_ledger import CandidateLifecycleEvent
from aisc_imis.member_ledger import MemberLedgerEntry
from aisc_imis.normalization_contracts import SourceReference


class FindingType(StrEnum):
    INFORMATION_GAP = "information_gap"
    UNCERTAIN_INFERENCE = "uncertain_inference"
    EVIDENCE_CONFLICT = "evidence_conflict"
    IMPOSSIBLE_TRANSITION = "impossible_transition"
    BALANCE_DIFFERENCE = "balance_difference"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ReviewState(StrEnum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    CONFIRMED = "confirmed"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class FindingRule:
    type: FindingType
    default_severity: Severity
    recommended_action: str


_GAP = FindingRule(
    FindingType.INFORMATION_GAP,
    Severity.INFO,
    "Locate missing source evidence; keep the affected state unknown until reviewed.",
)
_UNCERTAIN = FindingRule(
    FindingType.UNCERTAIN_INFERENCE,
    Severity.WARNING,
    "Review the source meaning and applicable rule before accepting an inference.",
)
_CONFLICT = FindingRule(
    FindingType.EVIDENCE_CONFLICT,
    Severity.ERROR,
    "Compare all cited sources and document a reviewed resolution.",
)
_TRANSITION = FindingRule(
    FindingType.IMPOSSIBLE_TRANSITION,
    Severity.ERROR,
    "Review the event sequence and source dates; correct only through an audited correction.",
)
_BALANCE = FindingRule(
    FindingType.BALANCE_DIFFERENCE,
    Severity.ERROR,
    "Reconcile opening count, movements, and closing count with source evidence.",
)

# Explicit entries prevent a new producer code from silently falling into a
# misleading category. Future reconciliation producers can add reviewed codes.
FINDING_RULES: dict[str, FindingRule] = {
    "missing_lifecycle_date": _GAP,
    "unknown_starting_state": _GAP,
    "unassessable_countability_snapshot": _GAP,
    "unassessable_state_field": _GAP,
    "missing_member_type": _GAP,
    "missing_is_company": _GAP,
    "missing_is_member": _GAP,
    "no_applicable_rule_version": _GAP,
    "unresolved_lifecycle_evidence": _UNCERTAIN,
    "unsupported_state_combination": _UNCERTAIN,
    "unsupported_transition": _UNCERTAIN,
    "invalid_snapshot_field": _UNCERTAIN,
    "same_day_state_contradiction": _CONFLICT,
    "company_dependent_conflict": _CONFLICT,
    "invalid_correction": _CONFLICT,
    "snapshot_state_conflict": _CONFLICT,
    "possible_missing_transition": _UNCERTAIN,
    "countability_difference": _CONFLICT,
    "repeated_lifecycle_event": _TRANSITION,
    "cyclic_correction": _TRANSITION,
    "balance_difference": _BALANCE,
}


@dataclass(frozen=True)
class ReconciliationFinding:
    """A stable identity plus separate, changeable review metadata."""

    id: str
    code: str
    type: FindingType
    subject_key: str | None
    scope: str
    severity: Severity
    review_state: ReviewState
    recommended_action: str
    supporting_evidence_ids: tuple[str, ...]
    contradicting_evidence_ids: tuple[str, ...]
    supporting_sources: tuple[SourceReference, ...]
    contradicting_sources: tuple[SourceReference, ...]

    @property
    def sources(self) -> tuple[SourceReference, ...]:
        """All source rows cited by this finding, in stable order."""
        return _ordered_sources((*self.supporting_sources, *self.contradicting_sources))


def build_finding(
    code: str,
    subject_key: str | None,
    scope: str,
    *,
    supporting_evidence: Iterable[MemberLedgerEntry] = (),
    contradicting_evidence: Iterable[MemberLedgerEntry] = (),
    severity: Severity | None = None,
    review_state: ReviewState = ReviewState.OPEN,
) -> ReconciliationFinding:
    """Classify a finding without changing the evidence or reconstructed state.

    ``scope`` identifies the date, period, or comparison within a member. Its
    value and the cited record IDs determine identity; severity, review state,
    and input order do not. ``subject_key=None`` is for aggregate findings.
    """
    if code not in FINDING_RULES:
        raise ValueError(f"Unknown finding code: {code!r}")
    if not scope or not scope.strip():
        raise ValueError("Finding scope must be nonblank.")
    if subject_key is not None and not subject_key.strip():
        raise ValueError("Finding subject_key must be nonblank when supplied.")
    if severity is not None and not isinstance(severity, Severity):
        raise ValueError("severity must be a Severity value")
    if not isinstance(review_state, ReviewState):
        raise ValueError("review_state must be a ReviewState value")
    supporting = tuple(supporting_evidence)
    contradicting = tuple(contradicting_evidence)
    for entry in (*supporting, *contradicting):
        if subject_key is None or entry.record.subject_key != subject_key:
            raise ValueError("Evidence subject_key must match the finding subject_key.")
    support_ids = tuple(sorted({entry.record_id for entry in supporting}))
    contradiction_ids = tuple(sorted({entry.record_id for entry in contradicting}))
    identity = json.dumps(
        [code, subject_key, scope, support_ids, contradiction_ids],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    finding_id = "finding-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
    rule = FINDING_RULES[code]
    return ReconciliationFinding(
        id=finding_id,
        code=code,
        type=rule.type,
        subject_key=subject_key,
        scope=scope,
        severity=severity or rule.default_severity,
        review_state=review_state,
        recommended_action=rule.recommended_action,
        supporting_evidence_ids=support_ids,
        contradicting_evidence_ids=contradiction_ids,
        supporting_sources=_sources_for(supporting),
        contradicting_sources=_sources_for(contradicting),
    )


def order_findings(
    findings: Iterable[ReconciliationFinding],
) -> tuple[ReconciliationFinding, ...]:
    """Order findings independently of producer or evidence input order."""
    return tuple(
        sorted(
            findings,
            key=lambda item: (
                item.subject_key or "",
                item.scope,
                item.code,
                item.id,
                item.severity.value,
                item.review_state.value,
            ),
        )
    )


def _sources_for(entries: tuple[MemberLedgerEntry, ...]) -> tuple[SourceReference, ...]:
    sources: list[SourceReference] = []
    for entry in entries:
        record = entry.record
        if isinstance(record, CandidateLifecycleEvent):
            sources.extend(record.source_references)
        else:
            sources.append(record.source_reference)
    return _ordered_sources(sources)


def _ordered_sources(sources: Iterable[SourceReference]) -> tuple[SourceReference, ...]:
    return tuple(
        sorted(set(sources), key=lambda item: (item.source_name, item.row_reference))
    )
