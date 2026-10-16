"""Local reviewer annotations for reconciliation findings.

Applying a review never changes a finding, its evidence, or its review state.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path

from aisc_imis.finding_taxonomy import ReconciliationFinding


class ReviewStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    ACCEPTED = "accepted"
    EXPLAINED = "explained"
    INACTIVE = "inactive"
    EXPIRED = "expired"
    STALE = "stale"


@dataclass(frozen=True)
class ReviewEntry:
    code: str
    member_key: str | None
    scope: str
    finding_id: str
    reviewer: str
    outcome: str
    rationale: str
    review_date: date
    valid_from: date | None = None
    valid_through: date | None = None

    @property
    def matching_key(self) -> tuple[str | None, str, str]:
        return (self.member_key, self.code, self.scope)


@dataclass(frozen=True)
class ReviewRegistry:
    entries: tuple[ReviewEntry, ...]


@dataclass(frozen=True)
class FindingAnnotation:
    finding: ReconciliationFinding
    review: ReviewEntry | None
    status: ReviewStatus


@dataclass(frozen=True)
class ReviewApplication:
    findings: tuple[FindingAnnotation, ...]
    unmatched_reviews: tuple[ReviewEntry, ...]


_REQUIRED = frozenset(
    {
        "code",
        "member_key",
        "scope",
        "finding_id",
        "reviewer",
        "outcome",
        "rationale",
        "review_date",
    }
)
_OPTIONAL = frozenset({"valid_from", "valid_through"})
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


def load_review_registry(path: str | Path) -> ReviewRegistry:
    """Load and validate a JSON registry containing a ``reviews`` list."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid review registry JSON: {error}") from error
    if not isinstance(data, dict) or set(data) != {"reviews"}:
        raise ValueError("Review registry must be an object with only a reviews list.")
    if not isinstance(data["reviews"], list):
        raise ValueError("Review registry reviews must be a list.")

    entries: list[ReviewEntry] = []
    seen: set[tuple[str | None, str, str]] = set()
    for number, raw in enumerate(data["reviews"], start=1):
        entry = _parse_entry(raw, number)
        if entry.matching_key in seen:
            raise ValueError(
                f"Duplicate review key at reviews[{number}]: {entry.matching_key!r}"
            )
        seen.add(entry.matching_key)
        entries.append(entry)
    return ReviewRegistry(tuple(entries))


def annotate_findings(
    findings: Iterable[ReconciliationFinding],
    registry: ReviewRegistry,
    *,
    as_of: date,
) -> ReviewApplication:
    """Return annotations and saved reviews with no current matching finding."""
    if not isinstance(as_of, date):
        raise ValueError("as_of must be a date")
    by_key = {entry.matching_key: entry for entry in registry.entries}
    matched: set[tuple[str | None, str, str]] = set()
    annotations: list[FindingAnnotation] = []
    for finding in findings:
        key = (finding.subject_key, finding.code, finding.scope)
        review = by_key.get(key)
        if review is None:
            annotations.append(
                FindingAnnotation(finding, None, ReviewStatus.UNREVIEWED)
            )
            continue
        matched.add(key)
        if review.finding_id != finding.id:
            status = ReviewStatus.STALE
        elif review.valid_from is not None and as_of < review.valid_from:
            status = ReviewStatus.INACTIVE
        elif review.valid_through is not None and as_of > review.valid_through:
            status = ReviewStatus.EXPIRED
        else:
            status = ReviewStatus(review.outcome)
        annotations.append(FindingAnnotation(finding, review, status))
    unmatched = tuple(
        entry for entry in registry.entries if entry.matching_key not in matched
    )
    return ReviewApplication(tuple(annotations), unmatched)


def _parse_entry(raw: object, number: int) -> ReviewEntry:
    label = f"reviews[{number}]"
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be an object.")
    missing = _REQUIRED - raw.keys()
    extra = raw.keys() - (_REQUIRED | _OPTIONAL)
    if missing or extra:
        raise ValueError(
            f"{label} has missing fields {sorted(missing)} or extra fields {sorted(extra)}."
        )
    member_key = raw["member_key"]
    if member_key is not None:
        member_key = _nonblank(raw, "member_key", label)
    outcome = _nonblank(raw, "outcome", label)
    if outcome not in {"accepted", "explained"}:
        raise ValueError(f"{label}.outcome must be accepted or explained.")
    valid_from = _date(raw, "valid_from", label) if "valid_from" in raw else None
    valid_through = (
        _date(raw, "valid_through", label) if "valid_through" in raw else None
    )
    if (
        valid_from is not None
        and valid_through is not None
        and valid_from > valid_through
    ):
        raise ValueError(f"{label}.valid_from must be on or before valid_through.")
    return ReviewEntry(
        code=_nonblank(raw, "code", label),
        member_key=member_key,
        scope=_nonblank(raw, "scope", label),
        finding_id=_nonblank(raw, "finding_id", label),
        reviewer=_nonblank(raw, "reviewer", label),
        outcome=outcome,
        rationale=_nonblank(raw, "rationale", label),
        review_date=_date(raw, "review_date", label),
        valid_from=valid_from,
        valid_through=valid_through,
    )


def _nonblank(raw: dict[str, object], field: str, label: str) -> str:
    value = raw[field]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}.{field} must be a nonblank string.")
    return value


def _date(raw: dict[str, object], field: str, label: str) -> date:
    value = raw[field]
    if not isinstance(value, str) or _ISO_DATE.fullmatch(value) is None:
        raise ValueError(f"{label}.{field} must be an ISO date (YYYY-MM-DD).")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(
            f"{label}.{field} must be a valid ISO date (YYYY-MM-DD)."
        ) from error
