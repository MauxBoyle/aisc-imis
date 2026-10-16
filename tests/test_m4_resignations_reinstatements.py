"""Synthetic M4 movements and their CSV export."""

import csv
from dataclasses import replace
from datetime import date
from pathlib import Path

from aisc_imis.board_pending_actions import BoardPendingActions
from aisc_imis.evidence_ledger import (
    CandidateLifecycleEvent,
    InterpretationStatus,
    SnapshotStateObservation,
)
from aisc_imis.lifecycle_rules import load_lifecycle_rules
from aisc_imis.m4_resignations_reinstatements import (
    build_m4_resignations_reinstatements,
    write_m4_csv,
)
from aisc_imis.member_ledger import build_member_evidence_ledger
from aisc_imis.normalization_contracts import SourceReference
from aisc_imis.quarterly_board_movements import classify_quarterly_movements

START, END = date(2027, 1, 1), date(2027, 4, 1)
RULES = load_lifecycle_rules(Path(__file__).parents[1] / "data/reference")


def snapshot(key, when, category="A", member_type="ACT"):
    return tuple(
        SnapshotStateObservation(
            key,
            f"{field}={value}",
            SourceReference("synthetic.csv", f"{key}-snapshot-{when}"),
            observed_date=when,
            recorded_date=when,
        )
        for field, value in (
            ("member_type", member_type),
            ("category", category),
            ("is_member", True),
            ("is_company", False),
        )
    )


def event(key, action, when, *, recorded=None, category=None, status=None):
    return CandidateLifecycleEvent(
        key,
        action,
        (SourceReference("synthetic.csv", f"{key}-{action}-{when}"),),
        "Synthetic state change",
        effective_date=when,
        recorded_date=recorded or when,
        category=category,
        interpretation_status=status or InterpretationStatus.VERIFIED,
    )


def classify(records, cutoff=date(2027, 4, 15)):
    return classify_quarterly_movements(
        build_member_evidence_ledger(records).entries,
        START,
        END,
        cutoff,
        RULES,
        BoardPendingActions((), ()),
        ("A", "B"),
    )


def test_resignation_and_reinstatement_in_one_period_reconcile():
    movements = classify(
        (
            *snapshot("001", date(2026, 12, 31)),
            event("001", "resigned", date(2027, 2, 1)),
            event("001", "reinstated", date(2027, 3, 1)),
        )
    )
    result = build_m4_resignations_reinstatements(movements)
    assert (result.counts, len(result.resignations), len(result.reinstatements)) == (
        {"resigned": 1, "reinstated": 1},
        1,
        1,
    )
    assert result.resignations[0].operational_status == "former_member"
    assert result.reinstatements[0].operational_status == "current_member"
    assert result.resignations[0].member_type == "ACT"
    assert result.resignations[0].ledger_evidence_refs.startswith("ledger:")
    assert "synthetic.csv:001-resigned" in result.resignations[0].ledger_evidence_refs
    assert movements.operational_balance.overall.movements["resigned"] == 1
    assert movements.operational_balance.overall.movements["reinstated"] == 1


def test_backdated_action_obeys_recorded_cutoff():
    records = (
        *snapshot("001", date(2026, 12, 31)),
        event("001", "resigned", date(2027, 2, 1), recorded=date(2027, 4, 10)),
    )
    early = build_m4_resignations_reinstatements(classify(records, date(2027, 4, 5)))
    late = build_m4_resignations_reinstatements(classify(records))
    assert early.resignations == ()
    assert late.resignations[0].effective_date == date(2027, 2, 1)
    assert late.resignations[0].recorded_date == date(2027, 4, 10)
    assert late.resignations[0].report_cutoff == date(2027, 4, 15)


def test_category_transfer_stays_separate_and_action_category_is_retained():
    records = (
        *snapshot("001", date(2026, 12, 31)),
        *snapshot("001", date(2027, 1, 15), category="B"),
        event("001", "resigned", date(2027, 2, 1)),
        event("001", "reinstated", date(2027, 3, 1)),
    )
    movements = classify(records)
    result = build_m4_resignations_reinstatements(movements)
    assert len(movements.category_transfers) == 1
    assert [row.category for row in (*result.resignations, *result.reinstatements)] == [
        "B",
        "B",
    ]
    assert result.counts == {"resigned": 1, "reinstated": 1}


def test_duplicate_and_uncertain_events_do_not_create_extra_rows():
    repeated = event("001", "resigned", date(2027, 2, 1))
    movements = classify(
        (
            *snapshot("001", date(2026, 12, 31)),
            repeated,
            repeated,
            event(
                "001",
                "reinstated",
                date(2027, 3, 1),
                status=InterpretationStatus.AMBIGUOUS,
            ),
        )
    )
    result = build_m4_resignations_reinstatements(movements)
    assert len(result.resignations) == 1
    assert result.reinstatements == ()
    assert result.findings


def test_conflicting_evidence_and_incomplete_balance_remain_findings():
    movements = classify(
        (
            *snapshot("known", date(2026, 12, 31)),
            event("known", "resigned", date(2027, 2, 1)),
            *snapshot("unknown", date(2027, 1, 15)),
            event(
                "unknown",
                "resigned",
                date(2027, 3, 1),
                status=InterpretationStatus.AMBIGUOUS,
            ),
        )
    )
    result = build_m4_resignations_reinstatements(movements)
    assert len(result.resignations) == 1
    assert movements.operational_balance.overall.difference is None
    assert {finding.code for finding in movements.findings} <= {
        finding.code for finding in result.findings
    }
    assert "unresolved_lifecycle_evidence" in {
        finding.code for finding in result.findings
    }


def test_missing_action_evidence_and_count_difference_are_reported():
    movements = classify(
        (
            *snapshot("001", date(2026, 12, 31)),
            event("001", "resigned", date(2027, 2, 1)),
        )
    )
    counted = replace(movements.counted[0], evidence=())
    inconsistent = replace(movements, counted=(counted,))
    result = build_m4_resignations_reinstatements(inconsistent)
    assert result.resignations == ()
    assert result.counts["resigned"] == 0
    assert {finding.code for finding in result.findings} >= {
        "m4_missing_state_change_evidence",
        "m4_classified_count_difference",
        "m4_balance_count_difference",
    }


def test_csv_has_headers_dates_status_and_evidence(tmp_path):
    movements = classify(
        (
            *snapshot("001", date(2026, 12, 31)),
            event("001", "resigned", date(2027, 2, 1)),
            event("001", "reinstated", date(2027, 3, 1)),
        )
    )
    result = build_m4_resignations_reinstatements(movements)
    resignation_path, reinstatement_path = write_m4_csv(result, tmp_path / "reports")
    with resignation_path.open(newline="", encoding="utf-8") as file:
        resigned = list(csv.DictReader(file))
    with reinstatement_path.open(newline="", encoding="utf-8") as file:
        reinstated = list(csv.DictReader(file))
    assert len(resigned) == len(reinstated) == 1
    assert resigned[0]["subject_key"] == "001"
    assert resigned[0]["effective_date"] == "2027-02-01"
    assert resigned[0]["operational_status"] == "former_member"
    assert reinstated[0]["operational_status"] == "current_member"
    assert "ledger:" in resigned[0]["ledger_evidence_refs"]
