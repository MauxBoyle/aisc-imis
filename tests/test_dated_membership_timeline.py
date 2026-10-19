"""Issue 73: effective membership dates and evidence availability differ."""

from datetime import date
from pathlib import Path

from aisc_imis.evidence_ledger import (
    CandidateLifecycleEvent,
    ObservedFact,
    SnapshotStateObservation,
)
from aisc_imis.lifecycle_period_movements import analyze_period_membership_movements
from aisc_imis.lifecycle_reconstruction import (
    LifecycleState,
    reconstruct_member_lifecycle,
)
from aisc_imis.lifecycle_rules import load_lifecycle_rules
from aisc_imis.member_ledger import build_member_evidence_ledger
from aisc_imis.normalization_contracts import SourceReference
from aisc_imis.operational_membership_summary import summarize_operational_membership

RULES = load_lifecycle_rules(Path(__file__).parents[1] / "data" / "reference")


def snapshot(kind: str, observed: date, row: str):
    ref = SourceReference("snap.csv", row)
    return tuple(
        SnapshotStateObservation("firm", f"{field}={value}", ref, recorded_date=observed, observed_date=observed)
        for field, value in (("member_type", kind), ("is_company", True), ("is_member", True), ("category", "A"))
    )


def join(when: date, observed: date, row: str = "join"):
    return ObservedFact("firm", "join_date", when.isoformat(), SourceReference("snap.csv", row), recorded_date=observed, observed_date=observed)


def event(name: str, effective: date | None, recorded: date, row: str = "event"):
    return CandidateLifecycleEvent("firm", name, (SourceReference("events.csv", row),), "synthetic", effective_date=effective, recorded_date=recorded)


def result(records, start: date, end: date, cutoff: date):
    return analyze_period_membership_movements(build_member_evidence_ledger(records).entries, start, end, RULES, knowledge_cutoff=cutoff)


def test_later_snapshot_supports_september_join_only_after_knowledge_cutoff():
    records = (join(date(2026, 9, 16), date(2026, 10, 15)), *snapshot("ACT", date(2026, 10, 15), "join"))
    later = result(records, date(2026, 7, 1), date(2026, 10, 1), date(2026, 10, 15))
    earlier = result(records, date(2026, 7, 1), date(2026, 10, 1), date(2026, 9, 30))
    assert later.gross_lifecycle_actions == {"joined": 1}
    assert later.contributors[0].dated_actions[0].effective_date == date(2026, 9, 16)
    assert earlier.gross_lifecycle_actions == {}
    entries = build_member_evidence_ledger(records).entries
    assert reconstruct_member_lifecycle(entries, date(2026, 9, 30), RULES, knowledge_cutoff=date(2026, 10, 15)).state is LifecycleState.CURRENT_MEMBER
    assert reconstruct_member_lifecycle(entries, date(2026, 9, 30), RULES, knowledge_cutoff=date(2026, 9, 30)).state is LifecycleState.UNKNOWN
    operational = summarize_operational_membership(entries, date(2026, 9, 30), date(2026, 6, 30), ("A",), RULES, knowledge_cutoff=date(2026, 10, 15))
    assert operational.overall.confirmed_count == 1
    assert operational.overall.total == 1


def test_join_on_first_day_of_next_quarter_stays_out_of_previous_quarter():
    records = (join(date(2026, 10, 1), date(2026, 10, 15)), *snapshot("ACT", date(2026, 10, 15), "join"))
    assert result(records, date(2026, 7, 1), date(2026, 10, 1), date(2026, 10, 15)).gross_lifecycle_actions == {}
    assert result(records, date(2026, 10, 1), date(2027, 1, 1), date(2027, 1, 1)).gross_lifecycle_actions == {"joined": 1}


def test_dated_expulsion_is_q1_exit_and_june_snapshot_only_confirms_state():
    records = (join(date(2025, 4, 1), date(2026, 1, 1)), *snapshot("ACT", date(2026, 1, 1), "member"), event("expelled", date(2026, 3, 1), date(2026, 3, 3)), *snapshot("FACT", date(2026, 6, 1), "former"))
    q1 = result(records, date(2026, 1, 1), date(2026, 4, 1), date(2026, 6, 1))
    q2 = result(records, date(2026, 4, 1), date(2026, 7, 1), date(2026, 6, 30))
    assert q1.gross_lifecycle_actions == {"expelled": 1}
    assert q2.gross_lifecycle_actions == {}


def test_undated_exit_and_snapshot_change_have_unknown_movement_quarter():
    records = (join(date(2025, 4, 1), date(2026, 1, 1)), *snapshot("ACT", date(2026, 1, 1), "member"), event("expelled", None, date(2026, 3, 3)), *snapshot("FACT", date(2026, 6, 1), "former"))
    q2 = result(records, date(2026, 4, 1), date(2026, 7, 1), date(2026, 6, 30))
    assert q2.gross_lifecycle_actions == {}
    assert q2.net_population_change is None
    assert {item.code for item in q2.findings} >= {"missing_lifecycle_date", "undated_snapshot_change"}
    entries = build_member_evidence_ledger(records).entries
    assert reconstruct_member_lifecycle(entries, date(2026, 3, 31), RULES, knowledge_cutoff=date(2026, 6, 30)).state is LifecycleState.UNKNOWN
    observed = reconstruct_member_lifecycle(entries, date(2026, 6, 30), RULES, knowledge_cutoff=date(2026, 6, 30))
    assert observed.state is LifecycleState.FORMER_MEMBER
    assert any(item.code == "undated_snapshot_change" for item in observed.findings)


def test_conflicting_join_dates_are_findings_without_a_chosen_join():
    records = (join(date(2026, 9, 16), date(2026, 10, 15)), join(date(2026, 9, 17), date(2026, 10, 15), "other"), *snapshot("ACT", date(2026, 10, 15), "join"))
    q3 = result(records, date(2026, 7, 1), date(2026, 10, 1), date(2026, 10, 15))
    assert q3.gross_lifecycle_actions == {}
    assert any(item.code == "conflicting_join_dates" for item in q3.findings)


def test_explicit_reinstatement_overrides_same_day_join_date():
    when = date(2026, 9, 16)
    records = (
        *snapshot("FACT", date(2026, 8, 1), "former"),
        join(when, date(2026, 10, 15)),
        event("reinstated", when, date(2026, 9, 17)),
        *snapshot("ACT", date(2026, 10, 15), "current"),
    )

    q3 = result(records, date(2026, 7, 1), date(2026, 10, 1), date(2026, 10, 15))

    assert q3.gross_lifecycle_actions == {"reinstated": 1}
    assert q3.contributors[0].dated_actions[0].date_basis == "event_effective_date"
    assert any(
        isinstance(entry.record, CandidateLifecycleEvent) and entry.record.event_name == "reinstated"
        for entry in q3.contributors[0].dated_actions[0].supporting_evidence
    )


def test_earlier_member_snapshot_makes_later_join_date_a_reinstatement():
    when = date(2026, 9, 16)
    records = (
        *snapshot("ACT", date(2026, 6, 1), "earlier-member"),
        event("resigned", date(2026, 8, 1), date(2026, 8, 2), "resigned"),
        join(when, date(2026, 10, 15)),
        *snapshot("ACT", date(2026, 10, 15), "current"),
    )

    q3 = result(records, date(2026, 7, 1), date(2026, 10, 1), date(2026, 10, 15))

    assert q3.gross_lifecycle_actions == {"resigned": 1, "reinstated": 1}
    assert q3.contributors[0].dated_actions[-1].date_basis == "join_date"


def test_earlier_nonmember_account_does_not_make_join_a_reinstatement():
    records = (
        *snapshot("FACT", date(2026, 6, 1), "earlier-account"),
        join(date(2026, 9, 16), date(2026, 10, 15)),
        *snapshot("ACT", date(2026, 10, 15), "current"),
    )

    q3 = result(records, date(2026, 7, 1), date(2026, 10, 1), date(2026, 10, 15))

    assert q3.gross_lifecycle_actions == {"joined": 1}
