"""Synthetic M4 movements and their CSV export."""

import csv
from dataclasses import replace
from datetime import date
from pathlib import Path

from aisc_imis.board_pending_actions import BoardPendingActions
from aisc_imis.evidence_ledger import (
    CandidateLifecycleEvent,
    InterpretationStatus,
    ObservedFact,
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


def snapshot(key, when, category="A", member_type="ACT", is_company=False):
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
            ("is_company", is_company),
        )
        if value is not None
    )


def event(key, action, when, *, recorded=None, category=None, member_type=None, status=None):
    return CandidateLifecycleEvent(
        key,
        action,
        (SourceReference("synthetic.csv", f"{key}-{action}-{when}"),),
        "Synthetic state change",
        effective_date=when,
        recorded_date=recorded or when,
        category=category,
        member_type=member_type,
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


def test_join_date_with_prior_membership_exports_reinstatement():
    when = date(2027, 3, 1)
    movements = classify(
        (
            *snapshot("001", date(2026, 12, 31), is_company=True),
            event("001", "resigned", date(2027, 2, 1)),
            ObservedFact("001", "join_date", when.isoformat(), SourceReference("synthetic.csv", "join-date"), recorded_date=date(2027, 4, 10)),
            *snapshot("001", date(2027, 4, 10), is_company=True),
        )
    )

    result = build_m4_resignations_reinstatements(movements)

    assert result.counts == {"resigned": 1, "reinstated": 1}
    assert result.reinstatements[0].effective_date == when
    assert result.reinstatements[0].date_basis == "join_date"


def test_join_date_reinstatement_uses_new_membership_attributes_and_csv(tmp_path):
    when = date(2027, 3, 1)
    records = (
        *snapshot("001", date(2026, 12, 31), is_company=True),
        event("001", "resigned", date(2027, 2, 1)),
        ObservedFact("001", "join_date", when.isoformat(), SourceReference("synthetic.csv", "join-date"), recorded_date=date(2027, 4, 10)),
        *snapshot("001", date(2027, 4, 10), category="B", member_type="ASSOC", is_company=True),
    )
    movements = classify(records)
    result = build_m4_resignations_reinstatements(movements)
    assert [(row.action, row.measure, row.category, row.member_type) for row in movements.counted] == [
        ("resigned", "M4", "A", "ACT"),
        ("reinstated", "M4", "B", "ASSOC"),
    ]
    assert result.counts == {"resigned": 1, "reinstated": 1}
    assert movements.membership_grouping_transfers == ()
    assert movements.category_transfers == ()
    _, path = write_m4_csv(result, tmp_path)
    with path.open(newline="", encoding="utf-8") as file:
        assert [(row["category"], row["member_type"]) for row in csv.DictReader(file)] == [("B", "ASSOC")]


def test_join_date_reinstatement_does_not_inherit_old_attributes(tmp_path):
    when = date(2027, 3, 1)
    records = (
        *snapshot("001", date(2026, 12, 31), is_company=True),
        event("001", "resigned", date(2027, 2, 1)),
        ObservedFact("001", "join_date", when.isoformat(), SourceReference("synthetic.csv", "join-date"), recorded_date=date(2027, 4, 10)),
        *snapshot("001", date(2027, 4, 10), category=None, member_type=None, is_company=True),
    )
    movements = classify(records)
    result = build_m4_resignations_reinstatements(movements)
    assert result.counts == {"resigned": 1, "reinstated": 1}
    assert (result.reinstatements[0].category, result.reinstatements[0].member_type) == (None, None)
    assert (movements.movement.contributors[0].closing_category, movements.movement.contributors[0].closing_member_type) == (None, None)
    _, path = write_m4_csv(result, tmp_path)
    with path.open(newline="", encoding="utf-8") as file:
        row = next(csv.DictReader(file))
    assert (row["category"], row["member_type"]) == ("", "")


def test_partial_new_snapshot_supplies_only_its_known_attribute():
    when = date(2027, 3, 1)
    records = (
        *snapshot("001", date(2026, 12, 31), is_company=True),
        event("001", "resigned", date(2027, 2, 1)),
        ObservedFact("001", "join_date", when.isoformat(), SourceReference("synthetic.csv", "join-date"), recorded_date=date(2027, 4, 10)),
        *snapshot("001", date(2027, 4, 10), category="B", member_type=None, is_company=True),
    )
    result = build_m4_resignations_reinstatements(classify(records))
    assert result.counts == {"resigned": 1, "reinstated": 1}
    assert (result.reinstatements[0].category, result.reinstatements[0].member_type) == ("B", None)


def test_prior_member_explicit_join_is_reinstatement_with_undated_exit():
    when = date(2027, 3, 1)
    records = (
        *snapshot("001", date(2026, 12, 31)),
        event("001", "joined", when, category="B", member_type="ASSOC"),
    )
    movements = classify(records)
    result = build_m4_resignations_reinstatements(movements)
    assert [(row.action, row.measure) for row in movements.counted] == [("reinstated", "M4")]
    assert result.counts == {"resigned": 0, "reinstated": 1}
    assert (result.reinstatements[0].category, result.reinstatements[0].member_type) == ("B", "ASSOC")
    assert movements.operational_balance.overall.difference is None
    assert "undated_snapshot_change" in {finding.code for finding in result.findings}


def test_prior_member_explicit_join_obeys_period_and_report_cutoff():
    records = (
        *snapshot("001", date(2026, 12, 31)),
        event("001", "joined", END, recorded=date(2027, 4, 10)),
    )
    assert build_m4_resignations_reinstatements(classify(records)).reinstatements == ()
    in_period = (
        *snapshot("001", date(2026, 12, 31)),
        event("001", "joined", date(2027, 3, 31), recorded=date(2027, 4, 10)),
    )
    assert build_m4_resignations_reinstatements(classify(in_period, date(2027, 4, 5))).reinstatements == ()
    assert len(build_m4_resignations_reinstatements(classify(in_period)).reinstatements) == 1


def test_prior_membership_without_dated_exit_keeps_m4_balance_incomplete():
    when = date(2027, 3, 1)
    movements = classify(
        (
            *snapshot("001", date(2026, 12, 31), is_company=True),
            ObservedFact("001", "join_date", when.isoformat(), SourceReference("synthetic.csv", "join-date"), recorded_date=date(2027, 4, 10)),
            *snapshot("001", date(2027, 4, 10), is_company=True),
        )
    )

    result = build_m4_resignations_reinstatements(movements)

    assert result.counts == {"resigned": 0, "reinstated": 1}
    assert movements.operational_balance.overall.difference is None


def test_explicit_reinstatement_with_same_day_join_date_exports_to_m4():
    when = date(2027, 3, 1)
    movements = classify(
        (
            ObservedFact("001", "join_date", when.isoformat(), SourceReference("synthetic.csv", "join-date"), recorded_date=date(2027, 4, 10)),
            event("001", "reinstated", when),
            *snapshot("001", date(2027, 4, 10), is_company=True),
        )
    )

    result = build_m4_resignations_reinstatements(movements)

    assert result.counts == {"resigned": 0, "reinstated": 1}
    assert result.reinstatements[0].date_basis == "event_effective_date"
    assert movements.operational_balance.overall.difference is None


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
        None,
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
