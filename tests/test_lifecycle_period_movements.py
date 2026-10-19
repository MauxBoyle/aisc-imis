"""Synthetic acceptance tests for inclusive-start, exclusive-end movements."""

from datetime import date
from pathlib import Path

from aisc_imis.evidence_ledger import CandidateLifecycleEvent, SnapshotStateObservation
from aisc_imis.lifecycle_period_movements import (
    EvidenceCorrection,
    analyze_period_membership_movements,
)
from aisc_imis.lifecycle_rules import load_lifecycle_rules
from aisc_imis.member_ledger import build_member_evidence_ledger
from aisc_imis.normalization_contracts import SourceReference

RULES = load_lifecycle_rules(Path(__file__).parents[1] / "data" / "reference")


def snapshots(member_type, category, when, row):
    return tuple(
        SnapshotStateObservation("member-1", f"{field}={value}", SourceReference("synthetic.csv", row), observed_date=when, recorded_date=when)
        for field, value in (("member_type", member_type), ("category", category), ("is_member", True), ("is_company", False))
    )


def analyze(records, corrections=()):
    entries = build_member_evidence_ledger(records).entries_for("member-1")
    return analyze_period_membership_movements(entries, date(2026, 10, 16), date(2026, 10, 20), RULES, corrections)


def test_grouping_category_and_combined_transfers_do_not_change_population():
    result = analyze((*snapshots("ACT", "A", date(2026, 10, 15), "open"), *snapshots("ASSOC", "B", date(2026, 10, 16), "move")))

    assert result.net_population_change == 0
    assert [(item.outgoing, item.incoming) for item in result.membership_grouping_transfers] == [("ACT", "ASSOC")]
    assert [(item.outgoing, item.incoming) for item in result.category_transfers] == [("A", "B")]


def test_countable_to_uncountable_snapshot_change_is_not_a_transfer():
    result = analyze((*snapshots("ACT", "A", date(2026, 10, 15), "open"), *snapshots("FACT", "B", date(2026, 10, 16), "closed")))

    assert result.net_population_change is None
    assert result.gross_lifecycle_actions == {}
    assert any(item.code == "undated_snapshot_change" for item in result.findings)
    assert result.membership_grouping_transfers == ()
    assert result.category_transfers == ()


def test_transferred_event_and_same_day_snapshot_merge_without_a_contradiction():
    records = (
        *snapshots("ACT", "A", date(2026, 10, 15), "open"),
        CandidateLifecycleEvent("member-1", "transferred", (SourceReference("synthetic.csv", "transfer"),), "synthetic", member_type="ASSOC", category="B", effective_date=date(2026, 10, 16), recorded_date=date(2026, 10, 16)),
        *snapshots("ASSOC", "B", date(2026, 10, 16), "moved"),
    )

    result = analyze(records)

    assert not any(finding.code == "same_day_state_contradiction" for finding in result.findings)
    assert result.net_population_change == 0
    assert [(item.outgoing, item.incoming) for item in result.membership_grouping_transfers] == [("ACT", "ASSOC")]
    assert [(item.outgoing, item.incoming) for item in result.category_transfers] == [("A", "B")]


def test_gross_actions_remain_visible_when_join_and_exit_cancel_net_change():
    records = (
        *snapshots("FACT", "A", date(2026, 10, 15), "open"),
        CandidateLifecycleEvent("member-1", "joined", (SourceReference("synthetic.csv", "join"),), "synthetic", effective_date=date(2026, 10, 16), recorded_date=date(2026, 10, 16)),
        CandidateLifecycleEvent("member-1", "resigned", (SourceReference("synthetic.csv", "leave"),), "synthetic", effective_date=date(2026, 10, 17), recorded_date=date(2026, 10, 17)),
    )
    result = analyze(records)

    assert result.gross_lifecycle_actions == {"joined": 1, "resigned": 1}
    assert result.net_population_change == 0


def test_correction_changes_opening_evidence_without_becoming_an_action():
    records = (*snapshots("FACT", "A", date(2026, 10, 15), "wrong"), *snapshots("ACT", "A", date(2026, 10, 15), "right"))
    ledger = build_member_evidence_ledger(records)
    wrong = next(entry for entry in ledger.entries if entry.record.source_reference.row_reference == "wrong" and entry.record.state_name == "member_type=FACT")
    right = next(entry for entry in ledger.entries if entry.record.source_reference.row_reference == "right" and entry.record.state_name == "member_type=ACT")
    correction = EvidenceCorrection("member-1", wrong.record_id, right.record_id, (SourceReference("review.csv", "1"),), "Synthetic correction", recorded_date=date(2026, 10, 16))
    result = analyze_period_membership_movements(ledger.entries_for("member-1"), date(2026, 10, 16), date(2026, 10, 20), RULES, (correction,))

    assert result.applied_corrections == (correction,)
    assert result.gross_lifecycle_actions == {}
    assert result.net_population_change == 0


def test_repeated_conflicting_and_invalid_sequences_become_findings():
    opening = snapshots("ACT", "A", date(2026, 10, 15), "open")
    repeated = CandidateLifecycleEvent("member-1", "joined", (SourceReference("synthetic.csv", "repeat"),), "synthetic", effective_date=date(2026, 10, 16), recorded_date=date(2026, 10, 16))
    joined = CandidateLifecycleEvent("member-1", "joined", (SourceReference("synthetic.csv", "join"),), "synthetic", effective_date=date(2026, 10, 17), recorded_date=date(2026, 10, 17))
    resigned = CandidateLifecycleEvent("member-1", "resigned", (SourceReference("synthetic.csv", "leave"),), "synthetic", effective_date=date(2026, 10, 17), recorded_date=date(2026, 10, 17))
    ledger = build_member_evidence_ledger((*opening, repeated, joined, resigned))
    invalid = EvidenceCorrection("other-member", ledger.entries[0].record_id, ledger.entries[1].record_id, (SourceReference("review.csv", "2"),), "Wrong subject")
    result = analyze_period_membership_movements(ledger.entries_for("member-1"), date(2026, 10, 16), date(2026, 10, 20), RULES, (invalid,))

    assert {finding.code for finding in result.findings} >= {
        "invalid_correction",
        "undated_snapshot_change",
        "same_day_state_contradiction",
    }
