"""Pending Board actions use invented members and document references."""

import json
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path

import pytest

from aisc_imis.board_pending_actions import (
    ActionKind,
    ActionStatus,
    load_board_pending_actions,
)


def _revision(**changes):
    revision = {
        "action_id": "action-1",
        "revision_id": "revision-1",
        "member_ref": "invented-member-1",
        "action_kind": "new-member-approval",
        "status": "proposed",
        "status_date": "2026-10-01",
        "recorded_by": "Example Secretary",
        "rationale": "Invented Board packet entry.",
        "source_document_ref": "invented-packet-1/page-2",
    }
    revision.update(changes)
    return revision


def _load(tmp_path, revisions, *, version=1):
    path = tmp_path / "board_pending_actions.json"
    path.write_text(
        json.dumps({"version": version, "revisions": revisions}), encoding="utf-8"
    )
    return load_board_pending_actions(path)


@pytest.mark.parametrize("status", list(ActionStatus))
def test_all_statuses_are_loaded_without_losing_provenance(tmp_path, status):
    extra = (
        {"imis_record_ref": "invented-imis-entry-1"}
        if status is ActionStatus.RECORDED_IN_IMIS
        else {}
    )
    result = _load(tmp_path, [_revision(status=status.value, **extra)])

    assert result.actions[0].current_revision.status is status
    assert result.actions[0].current_revision.status_date == date(2026, 10, 1)
    assert (
        result.actions[0].current_revision.source_document_ref
        == "invented-packet-1/page-2"
    )
    assert result.possible_duplicates == ()
    with pytest.raises(FrozenInstanceError):
        result.actions[0].current_revision.rationale = "changed"


def test_empty_template_and_all_action_kinds(tmp_path):
    template = Path(__file__).resolve().parents[1] / "config/board_pending_actions.json"
    assert load_board_pending_actions(template).actions == ()
    assert _load(tmp_path, []).actions == ()
    result = _load(
        tmp_path,
        [
            _revision(),
            _revision(
                action_id="action-2",
                revision_id="revision-2",
                action_kind="expulsion",
                member_ref="invented-member-2",
                status="approved",
                effective_date="2026-11-01",
                imis_id="invented-imis-id-2",
            ),
            _revision(
                action_id="action-3",
                revision_id="revision-3",
                action_kind="correction",
                member_ref="invented-member-3",
                desired_countable=False,
                desired_category="Invented Category",
                desired_member_type="Invented Type",
            ),
        ],
    )
    assert [action.kind for action in result.actions] == list(ActionKind)
    assert result.actions[1].current_revision.effective_date == date(2026, 11, 1)
    assert result.actions[1].current_revision.imis_id == "invented-imis-id-2"
    assert result.actions[2].current_revision.desired_countable is False


def test_revision_chain_retains_each_status_and_source(tmp_path):
    result = _load(
        tmp_path,
        [
            _revision(),
            _revision(
                revision_id="revision-2",
                prior_revision_id="revision-1",
                status="approved",
                status_date="2026-10-03",
                source_document_ref="invented-minutes/page-4",
            ),
            _revision(
                revision_id="revision-3",
                prior_revision_id="revision-2",
                status="recorded-in-iMIS",
                status_date="2026-10-05",
                source_document_ref="invented-entry-log/row-1",
                imis_record_ref="invented-imis-entry-1",
            ),
        ],
    )
    assert len(result.actions) == 1
    assert [revision.status for revision in result.actions[0].revisions] == [
        ActionStatus.PROPOSED,
        ActionStatus.APPROVED,
        ActionStatus.RECORDED_IN_IMIS,
    ]
    assert (
        result.actions[0].revisions[0].source_document_ref == "invented-packet-1/page-2"
    )
    assert result.actions[0].current_revision.imis_record_ref == "invented-imis-entry-1"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"status": "pending"}, "status"),
        ({"action_kind": "other"}, "action_kind"),
        ({"status_date": "2026-02-30"}, "status_date"),
        ({"effective_date": "10/01/2026"}, "effective_date"),
        ({"member_ref": " "}, "member_ref"),
        ({"rationale": None}, "rationale"),
        ({"source_document_ref": ""}, "source_document_ref"),
        ({"status": "recorded-in-iMIS"}, "imis_record_ref"),
        ({"desired_countable": True}, "desired_countable"),
        ({"unexpected": "value"}, "unexpected"),
    ],
)
def test_invalid_revisions_have_clear_errors(tmp_path, changes, message):
    with pytest.raises(ValueError, match=message):
        _load(tmp_path, [_revision(**changes)])


@pytest.mark.parametrize(
    "field",
    [
        "action_id",
        "revision_id",
        "member_ref",
        "action_kind",
        "status",
        "status_date",
        "recorded_by",
        "rationale",
        "source_document_ref",
    ],
)
def test_missing_required_field(tmp_path, field):
    revision = _revision()
    del revision[field]
    with pytest.raises(ValueError, match=field):
        _load(tmp_path, [revision])


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({}, "desired"),
        ({"desired_countable": "false"}, "desired_countable"),
        ({"desired_category": ""}, "desired_category"),
        ({"desired_member_type": None}, "desired_member_type"),
    ],
)
def test_correction_requires_valid_target(tmp_path, changes, message):
    with pytest.raises(ValueError, match=message):
        _load(tmp_path, [_revision(action_kind="correction", **changes)])


@pytest.mark.parametrize(
    ("second", "message"),
    [
        ({"prior_revision_id": "missing"}, "prior_revision_id"),
        (
            {"prior_revision_id": "revision-1", "member_ref": "invented-member-2"},
            "member_ref",
        ),
        (
            {"prior_revision_id": "revision-1", "action_kind": "expulsion"},
            "action_kind",
        ),
        (
            {"prior_revision_id": "revision-1", "status_date": "2026-09-30"},
            "status_date",
        ),
        (
            {"prior_revision_id": "revision-1", "revision_id": "revision-1"},
            "revision_id",
        ),
    ],
)
def test_broken_revision_chains_are_rejected(tmp_path, second, message):
    with pytest.raises(ValueError, match=message):
        _load(
            tmp_path,
            [_revision(), _revision(**{"revision_id": "revision-2", **second})],
        )


def test_branch_and_second_root_are_rejected(tmp_path):
    base = _revision()
    child = _revision(revision_id="revision-2", prior_revision_id="revision-1")
    with pytest.raises(ValueError, match="prior_revision_id"):
        _load(
            tmp_path,
            [
                base,
                child,
                _revision(revision_id="revision-3", prior_revision_id="revision-1"),
            ],
        )
    with pytest.raises(ValueError, match="prior_revision_id"):
        _load(tmp_path, [base, _revision(revision_id="revision-2")])


def test_duplicate_ids_are_rejected_and_possible_duplicate_actions_are_reported(
    tmp_path,
):
    with pytest.raises(ValueError, match="revision_id"):
        _load(tmp_path, [_revision(), _revision(action_id="action-2")])

    result = _load(
        tmp_path,
        [_revision(), _revision(action_id="action-2", revision_id="revision-2")],
    )
    assert len(result.actions) == 2
    assert len(result.possible_duplicates) == 1
    assert result.possible_duplicates[0].member_ref == "invented-member-1"
    assert result.possible_duplicates[0].action_kind is ActionKind.NEW_MEMBER_APPROVAL
    assert result.possible_duplicates[0].action_ids == ("action-1", "action-2")


def test_invalid_document_structure(tmp_path):
    path = tmp_path / "actions.json"
    for data, message in [
        ({"version": 2, "revisions": []}, "version"),
        ({"version": 1, "revisions": {}}, "revisions"),
        ({"version": 1, "revisions": [], "extra": True}, "extra"),
    ]:
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            load_board_pending_actions(path)
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        load_board_pending_actions(path)
