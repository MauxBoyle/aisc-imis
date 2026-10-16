"""Review registry behavior using invented finding and member keys."""

import json
from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from aisc_imis.finding_taxonomy import ReviewState, build_finding
from aisc_imis.review_registry import (
    ReviewStatus,
    annotate_findings,
    load_review_registry,
)


def _finding():
    return build_finding("balance_difference", "invented-member-1", "2026-10")


def _entry(**changes):
    finding = _finding()
    entry = {
        "code": finding.code,
        "member_key": finding.subject_key,
        "scope": finding.scope,
        "finding_id": finding.id,
        "reviewer": "Example Reviewer",
        "outcome": "accepted",
        "rationale": "Invented evidence explains this result.",
        "review_date": "2026-10-10",
    }
    entry.update(changes)
    return entry


def _load(tmp_path, entries):
    path = tmp_path / "reviews.json"
    path.write_text(json.dumps({"reviews": entries}), encoding="utf-8")
    return load_review_registry(path)


@pytest.mark.parametrize(
    ("changes", "as_of", "status", "outcome"),
    [
        (
            {"outcome": "accepted"},
            date(2026, 10, 15),
            ReviewStatus.ACCEPTED,
            "accepted",
        ),
        (
            {"outcome": "explained"},
            date(2026, 10, 15),
            ReviewStatus.EXPLAINED,
            "explained",
        ),
        (
            {"valid_from": "2026-10-16"},
            date(2026, 10, 15),
            ReviewStatus.INACTIVE,
            "accepted",
        ),
        (
            {"valid_through": "2026-10-14"},
            date(2026, 10, 15),
            ReviewStatus.EXPIRED,
            "accepted",
        ),
        (
            {"finding_id": "finding-old"},
            date(2026, 10, 15),
            ReviewStatus.STALE,
            "accepted",
        ),
        (
            {"finding_id": "finding-old", "valid_through": "2026-10-14"},
            date(2026, 10, 15),
            ReviewStatus.STALE,
            "accepted",
        ),
        (
            {"valid_from": "2026-10-15", "valid_through": "2026-10-15"},
            date(2026, 10, 15),
            ReviewStatus.ACCEPTED,
            "accepted",
        ),
    ],
)
def test_review_statuses_and_original_finding_are_unchanged(
    tmp_path, changes, as_of, status, outcome
):
    finding = _finding()
    registry = _load(tmp_path, [_entry(**changes)])

    result = annotate_findings((finding,), registry, as_of=as_of)

    assert result.findings[0].finding is finding
    assert result.findings[0].status is status
    assert result.findings[0].review.outcome == outcome
    assert result.unmatched_reviews == ()
    assert finding.review_state is ReviewState.OPEN
    assert finding.id == _finding().id
    with pytest.raises(FrozenInstanceError):
        result.findings[0].status = ReviewStatus.EXPIRED


@pytest.mark.parametrize(
    "changes",
    [
        {"code": "unknown_starting_state"},
        {"scope": "2026-11"},
        {"member_key": "invented-member-2"},
    ],
)
def test_changed_matching_key_is_unmatched(tmp_path, changes):
    registry = _load(tmp_path, [_entry(**changes)])

    result = annotate_findings((_finding(),), registry, as_of=date(2026, 10, 15))

    assert result.findings[0].status is ReviewStatus.UNREVIEWED
    assert result.findings[0].review is None
    assert result.unmatched_reviews == registry.entries


def test_empty_registry_and_aggregate_finding(tmp_path):
    aggregate = build_finding("balance_difference", None, "2026-10")
    empty = _load(tmp_path, [])
    assert (
        annotate_findings((aggregate,), empty, as_of=date(2026, 10, 15))
        .findings[0]
        .status
        is ReviewStatus.UNREVIEWED
    )

    registry = _load(tmp_path, [_entry(member_key=None, finding_id=aggregate.id)])
    result = annotate_findings((aggregate,), registry, as_of=date(2026, 10, 15))
    assert result.findings[0].status is ReviewStatus.ACCEPTED


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"outcome": "approved"}, "outcome"),
        ({"review_date": "2026-02-30"}, "review_date"),
        ({"review_date": "10/15/2026"}, "review_date"),
        ({"valid_from": "2026-13-01"}, "valid_from"),
        ({"valid_through": "bad"}, "valid_through"),
        ({"valid_from": "2026-10-20", "valid_through": "2026-10-19"}, "valid_from"),
        ({"reviewer": "  "}, "reviewer"),
        ({"rationale": ""}, "rationale"),
        ({"member_key": ""}, "member_key"),
        ({"finding_id": None}, "finding_id"),
        ({"extra": "value"}, "extra"),
    ],
)
def test_invalid_entries_have_clear_errors(tmp_path, changes, message):
    with pytest.raises(ValueError, match=message):
        _load(tmp_path, [_entry(**changes)])


def test_missing_required_field_and_duplicate_matching_key_are_rejected(tmp_path):
    missing = _entry()
    del missing["scope"]
    with pytest.raises(ValueError, match="scope"):
        _load(tmp_path, [missing])

    with pytest.raises(ValueError, match="Duplicate review key"):
        _load(tmp_path, [_entry(), _entry(finding_id="finding-other")])


def test_invalid_registry_structure_is_rejected(tmp_path):
    path = tmp_path / "reviews.json"
    path.write_text('{"reviews": {}}', encoding="utf-8")
    with pytest.raises(ValueError, match="reviews"):
        load_review_registry(path)
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        load_review_registry(path)
