"""Synthetic acceptance cases for dated operational membership summaries."""

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from aisc_imis.evidence_ledger import CandidateLifecycleEvent, SnapshotStateObservation
from aisc_imis.lifecycle_period_movements import EvidenceCorrection
from aisc_imis.lifecycle_rules import LifecycleRules, load_lifecycle_rules
from aisc_imis.member_ledger import build_member_evidence_ledger
from aisc_imis.normalization_contracts import SourceReference
from aisc_imis.operational_membership_summary import (
    select_reporting_month_ends,
    summarize_operational_membership,
)

RULES = load_lifecycle_rules(Path(__file__).parents[1] / "data" / "reference")
EARLY_RULES = LifecycleRules(
    tuple(
        replace(rule, effective_reporting_date=date(2020, 1, 1)) for rule in RULES.rules
    )
)


def snapshot(member, member_type, category, when, row):
    fields = (("member_type", member_type), ("is_member", True), ("is_company", False))
    if category is not None:
        fields = (*fields, ("category", category))
    return tuple(
        SnapshotStateObservation(
            member,
            f"{field}={value}",
            SourceReference("synthetic", row),
            observed_date=when,
            recorded_date=when,
        )
        for field, value in fields
    )


def event(member, name, when, row, *, category=None, member_type=None):
    return CandidateLifecycleEvent(
        member,
        name,
        (SourceReference("synthetic", row),),
        "synthetic",
        category=category,
        member_type=member_type,
        effective_date=when,
        recorded_date=when,
    )


def summary(records, as_of, prior, corrections=(), rules=RULES):
    entries = build_member_evidence_ledger(records).entries
    return summarize_operational_membership(
        entries, as_of, prior, ("A", "B"), rules, corrections
    )


@pytest.mark.parametrize(
    ("start", "end", "quarter_only", "expected"),
    [
        (
            date(2024, 1, 1),
            date(2024, 3, 31),
            False,
            (date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31)),
        ),
        (
            date(2024, 1, 1),
            date(2024, 9, 30),
            True,
            (date(2024, 3, 31), date(2024, 6, 30), date(2024, 9, 30)),
        ),
        (date(2025, 2, 1), date(2025, 2, 27), False, ()),
    ],
)
def test_month_end_selector(start, end, quarter_only, expected):
    assert (
        select_reporting_month_ends(start, end, quarter_ends_only=quarter_only)
        == expected
    )


@pytest.mark.parametrize(
    "as_of", [date(2024, 2, 29), date(2025, 1, 31), date(2026, 10, 20)]
)
def test_count_uses_evidence_through_the_requested_date(as_of):
    prior = date(as_of.year, as_of.month, 1)
    records = (
        *snapshot("m", "FACT", "A", prior, "opening"),
        event("m", "joined", as_of, "join", category="A", member_type="ACT"),
        event("m", "resigned", as_of + timedelta(days=1), "late"),
    )
    result = summary(records, as_of, prior, rules=EARLY_RULES)

    assert result.overall.confirmed_count == result.overall.total == 1
    assert result.categories["A"].total == 1
    assert result.member_types["ACT"].total == 1
    assert result.overall.contributors[0].subject_key == "m"
    assert {
        source.row_reference
        for entry in result.overall.contributors[0].supporting_evidence
        for source in (
            entry.record.source_references
            if isinstance(entry.record, CandidateLifecycleEvent)
            else (entry.record.source_reference,)
        )
    } >= {"opening", "join"}
    assert result.balance.start_date == prior.replace(day=prior.day + 1)
    assert result.balance.end_date.toordinal() == as_of.toordinal() + 1
    assert result.balance.overall.difference == 0
    assert result.balance.overall.movements["resigned"] == 0


def test_custom_cutoff_and_category_member_type_transfer():
    records = (
        *snapshot("m", "ACT", "A", date(2026, 10, 15), "opening"),
        *snapshot("m", "ASSOC", "B", date(2026, 10, 20), "transfer"),
    )
    result = summary(records, date(2026, 10, 20), date(2026, 10, 15))

    assert result.overall.total == 1
    assert result.categories["A"].total == 0
    assert result.categories["B"].total == 1
    assert result.member_types["ACT"].total == 0
    assert result.member_types["ASSOC"].total == 1
    assert (
        result.categories["B"].contributors == result.member_types["ASSOC"].contributors
    )
    assert (
        result.categories["B"]
        .contributors[0]
        .supporting_evidence[-1]
        .record.source_reference.row_reference
        == "transfer"
    )
    assert result.balance.categories["A"].transfers_out == 1
    assert result.balance.categories["B"].transfers_in == 1


def test_unknown_member_keeps_confirmed_count_and_indeterminate_balance():
    records = (
        *snapshot("known", "ACT", "A", date(2026, 10, 15), "known"),
        *snapshot("unknown", "ACT", "A", date(2026, 10, 20), "late"),
    )
    result = summary(records, date(2026, 10, 20), date(2026, 10, 15))

    assert result.overall.confirmed_count == 2
    assert result.overall.total is None
    assert result.categories["A"].total is None
    assert result.member_types["ACT"].total is None
    assert result.unknown_member_ids == ("unknown",)
    assert result.balance.overall.difference is None
    assert any(finding.code == "unknown_starting_state" for finding in result.findings)


def test_missing_category_exposes_coverage():
    records = (
        *snapshot("category_missing", "ACT", None, date(2026, 10, 15), "no-category"),
        *snapshot("type_missing", "ACT", "B", date(2026, 10, 15), "type-before"),
        event(
            "type_missing", "transferred", date(2026, 10, 20), "transfer", category="B"
        ),
    )
    result = summary(records, date(2026, 10, 20), date(2026, 10, 15))

    assert result.overall.total == 2
    assert result.categories["A"].total is None
    assert result.member_types["ACT"].total == 2
    assert "category_missing" in result.missing_category_member_ids
    assert any(finding.code == "unknown_category" for finding in result.findings)


def test_unresolved_member_type_makes_total_indeterminate():
    records = (
        *snapshot("known", "ACT", "A", date(2026, 10, 15), "known"),
        *snapshot("bad", "UNKNOWN", "B", date(2026, 10, 20), "bad"),
    )
    result = summary(records, date(2026, 10, 20), date(2026, 10, 15))

    assert result.overall.confirmed_count == 1
    assert result.overall.total is None
    assert result.unknown_member_ids == ("bad",)
    assert any(
        finding.code == "unresolved_lifecycle_evidence" for finding in result.findings
    )


def test_countable_event_without_member_type_is_reported_as_missing():
    result = summary(
        (event("m", "joined", date(2026, 10, 20), "join", category="A"),),
        date(2026, 10, 20),
        date(2026, 10, 15),
    )

    assert result.overall.confirmed_count == 1
    assert result.overall.total is None
    assert result.categories["A"].confirmed_count == 1
    assert result.member_types == {}
    assert result.missing_member_type_member_ids == ("m",)
    assert any(finding.code == "unknown_member_type" for finding in result.findings)


def test_future_only_member_does_not_make_earlier_total_unknown():
    records = (
        *snapshot("current", "ACT", "A", date(2026, 10, 15), "current"),
        *snapshot("future", "ACT", "A", date(2026, 11, 1), "future"),
    )
    result = summary(records, date(2026, 10, 20), date(2026, 10, 15))

    assert result.overall.total == 1
    assert result.unknown_member_ids == ()
    assert [item.subject_key for item in result.overall.contributors] == ["current"]


def test_correction_is_traced_and_nonzero_difference_is_visible():
    records = (
        *snapshot("m", "FACT", "A", date(2026, 10, 15), "m-open"),
        event(
            "m", "joined", date(2026, 10, 20), "wrong", category="B", member_type="ACT"
        ),
        event(
            "m", "joined", date(2026, 10, 20), "right", category="A", member_type="ACT"
        ),
        *snapshot("n", "FACT", "B", date(2026, 10, 15), "n-open"),
        *snapshot("n", "ACT", "B", date(2026, 10, 20), "n-close"),
    )
    entries = build_member_evidence_ledger(records).entries
    wrong = next(
        entry
        for entry in entries
        if isinstance(entry.record, CandidateLifecycleEvent)
        and entry.record.source_references[0].row_reference == "wrong"
    )
    right = next(
        entry
        for entry in entries
        if isinstance(entry.record, CandidateLifecycleEvent)
        and entry.record.source_references[0].row_reference == "right"
    )
    correction = EvidenceCorrection(
        "m",
        wrong.record_id,
        right.record_id,
        (SourceReference("review", "1"),),
        "reviewed event",
    )
    result = summarize_operational_membership(
        entries,
        date(2026, 10, 20),
        date(2026, 10, 15),
        ("A", "B"),
        RULES,
        (correction,),
    )

    assert result.overall.total == 2
    assert result.overall.contributors[0].applied_corrections == (correction,)
    assert result.balance.overall.difference == 1
    assert result.balance.categories["B"].difference == 1
    assert any(finding.code == "balance_difference" for finding in result.findings)


def test_invalid_dates_are_rejected():
    with pytest.raises(ValueError):
        summary((), date(2026, 10, 15), date(2026, 10, 15))
