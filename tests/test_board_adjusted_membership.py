"""Invented members exercise the Board overlay without private records."""

import json
from dataclasses import replace
from datetime import date

from aisc_imis.board_adjusted_membership import build_board_adjusted_membership
from aisc_imis.board_pending_actions import load_board_pending_actions
from aisc_imis.evidence_ledger import SnapshotStateObservation
from aisc_imis.lifecycle_rules import load_lifecycle_rules
from aisc_imis.member_ledger import build_member_evidence_ledger
from aisc_imis.normalization_contracts import SourceReference
from aisc_imis.operational_membership_summary import summarize_operational_membership

CUTOFF = date(2026, 10, 20)


def _operational(*members):
    records = []
    for key, member_type, category in members:
        for field, value in (
            ("member_type", member_type),
            ("category", category),
            ("is_member", True),
            ("is_company", False),
        ):
            records.append(
                SnapshotStateObservation(
                    key,
                    f"{field}={value}",
                    SourceReference("invented", key),
                    observed_date=date(2026, 10, 15),
                    recorded_date=date(2026, 10, 15),
                )
            )
    return summarize_operational_membership(
        build_member_evidence_ledger(records).entries,
        CUTOFF,
        date(2026, 10, 15),
        ("A", "B"),
        load_lifecycle_rules("data/reference"),
    )


def _action(action_id, member, kind="new-member-approval", status="approved", **extra):
    return {
        "action_id": action_id,
        "revision_id": f"{action_id}-1",
        "member_ref": member,
        "action_kind": kind,
        "status": status,
        "status_date": "2026-10-18",
        "recorded_by": "Invented Secretary",
        "rationale": "Invented Board reason",
        "source_document_ref": "invented-minutes/p1",
        **extra,
    }


def _pending(tmp_path, *revisions):
    path = tmp_path / "actions.json"
    path.write_text(
        json.dumps({"version": 1, "revisions": revisions}), encoding="utf-8"
    )
    return load_board_pending_actions(path)


def test_approved_addition_before_imis_and_missing_dimensions(tmp_path):
    operational = _operational(("existing", "ACT", "A"))
    pending = _pending(tmp_path, _action("add", "new"))
    view = build_board_adjusted_membership(operational, pending)

    assert view.operational is operational
    assert operational.overall.total == 1
    assert view.adjustments.overall == 1
    assert view.adjusted.overall.total == 2
    assert view.adjusted.categories["A"].total is None
    assert view.adjusted.member_types["ACT"].total is None
    assert view.decisions[0].action_id == "add"
    assert view.decisions[0].reason == "Invented Board reason"
    assert view.decisions[0].source_document_ref == "invented-minutes/p1"
    assert view.adjusted.overall.contributors[-1].action_id == "add"
    assert view.adjusted.overall.contributors[-1].reason == "Invented Board reason"
    assert (
        view.adjusted.overall.contributors[-1].source_document_ref
        == "invented-minutes/p1"
    )
    assert {finding.code for finding in view.findings} >= {
        "missing_category",
        "missing_member_type",
    }


def test_proposal_expulsion_and_post_cutoff_are_visible_without_adjustment(tmp_path):
    operational = _operational(("existing", "ACT", "A"))
    pending = _pending(
        tmp_path,
        _action("proposal", "existing", "expulsion", "proposed"),
        _action("future", "later", status_date="2026-10-21"),
        _action("future-effective", "later-2", effective_date="2026-10-21"),
    )
    view = build_board_adjusted_membership(operational, pending)
    assert view.adjustments.overall == 0
    assert view.adjusted.overall.total == 1
    assert {decision.disposition for decision in view.decisions} >= {
        "not-approved",
        "after-cutoff",
    }


def test_approved_expulsion_and_correction_change_each_breakdown(tmp_path):
    operational = _operational(("gone", "ACT", "A"), ("moved", "ACT", "A"))
    pending = _pending(
        tmp_path,
        _action("expel", "gone", "expulsion"),
        _action(
            "correct",
            "moved",
            "correction",
            desired_category="B",
            desired_member_type="ASSOC",
        ),
    )
    view = build_board_adjusted_membership(operational, pending)
    assert view.adjustments.overall == -1
    assert view.adjusted.overall.total == 1
    assert view.adjusted.categories["A"].total == 0
    assert view.adjusted.categories["B"].total == 1
    assert view.adjusted.member_types["ACT"].total == 0
    assert view.adjusted.member_types["ASSOC"].total == 1
    assert all(
        decision.reason and decision.source_document_ref
        for decision in view.decisions
        if decision.disposition == "applied"
    )


def test_revision_history_uses_status_at_cutoff_and_recording_requires_confirmation(
    tmp_path,
):
    operational = _operational()
    first = _action("add", "new", status="proposed")
    approved = {
        **first,
        "revision_id": "add-2",
        "prior_revision_id": "add-1",
        "status": "approved",
        "status_date": "2026-10-19",
    }
    recorded = {
        **approved,
        "revision_id": "add-3",
        "prior_revision_id": "add-2",
        "status": "recorded-in-iMIS",
        "status_date": "2026-10-20",
        "imis_record_ref": "invented-entry",
    }
    pending = _pending(tmp_path, first, approved, recorded)
    view = build_board_adjusted_membership(operational, pending)
    assert view.adjusted.overall.total == 1
    assert view.decisions[0].disposition == "applied"
    assert any(f.code == "recording_unconfirmed" for f in view.findings)

    confirmed = build_board_adjusted_membership(
        _operational(("new", "ACT", "A")), pending
    )
    assert confirmed.adjustments.overall == 0
    assert confirmed.decisions[0].disposition == "recorded"


def test_duplicate_conflict_and_unknown_state_are_skipped(tmp_path):
    operational = _operational(("known", "ACT", "A"))
    pending = _pending(
        tmp_path,
        _action("a", "new"),
        _action("b", "new"),
        _action("c", "known", "expulsion"),
        _action("d", "known", "correction", desired_countable=True),
        _action("e", "absent", "expulsion"),
    )
    view = build_board_adjusted_membership(operational, pending)
    assert view.adjustments.overall == 0
    assert {d.disposition for d in view.decisions} >= {
        "possible-duplicate",
        "conflict",
        "unknown-state",
    }


def test_exact_imis_id_takes_precedence_and_unknown_total_stays_unknown(tmp_path):
    operational = _operational(("known", "ACT", "A"))
    pending = _pending(
        tmp_path, _action("x", "wrong-ref", "expulsion", imis_id="known")
    )
    view = build_board_adjusted_membership(operational, pending)
    assert view.decisions[0].subject_key == "known"
    assert view.adjusted.overall.total == 0


def test_uncertain_member_is_skipped_and_total_remains_indeterminate(tmp_path):
    known = _operational(("uncertain", "ACT", "A"))
    operational = replace(
        known,
        overall=replace(known.overall, total=None),
        unknown_member_ids=("uncertain",),
    )
    pending = _pending(tmp_path, _action("expel", "uncertain", "expulsion"))
    view = build_board_adjusted_membership(operational, pending)
    assert view.decisions[0].disposition == "unknown-state"
    assert view.adjustments.overall == 0
    assert view.adjusted.overall.total is None
    assert any(f.code == "unknown_state" for f in view.findings)


def test_later_withdrawal_does_not_change_earlier_cutoff(tmp_path):
    approved = _action("add", "new")
    withdrawn = {
        **approved,
        "revision_id": "add-2",
        "prior_revision_id": "add-1",
        "status": "withdrawn",
        "status_date": "2026-10-21",
    }
    pending = _pending(tmp_path, approved, withdrawn)
    view = build_board_adjusted_membership(_operational(), pending)
    assert view.adjusted.overall.total == 1
    assert view.decisions[0].revision_id == "add-1"


def test_recorded_expulsion_stops_after_operational_state_confirms(tmp_path):
    approved = _action("expel", "gone", "expulsion")
    recorded = {
        **approved,
        "revision_id": "expel-2",
        "prior_revision_id": "expel-1",
        "status": "recorded-in-iMIS",
        "status_date": "2026-10-19",
        "imis_record_ref": "invented-entry",
    }
    view = build_board_adjusted_membership(
        _operational(("gone", "FACT", "A")),
        _pending(tmp_path, approved, recorded),
    )
    assert view.decisions[0].disposition == "recorded"
    assert view.adjustments.overall == 0


def test_category_outside_selected_codes_is_flagged(tmp_path):
    view = build_board_adjusted_membership(
        _operational(("member", "ACT", "A")),
        _pending(
            tmp_path,
            _action("correct", "member", "correction", desired_category="C"),
        ),
    )
    assert view.adjusted.overall.total == 1
    assert view.adjusted.categories["A"].total is None
    assert any(f.code == "unselected_category" for f in view.findings)
