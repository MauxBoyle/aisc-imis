"""Reconstruct a member's reviewed lifecycle state from ledger evidence.

The service is deliberately pure: callers provide evidence for one already
confirmed member and receive immutable intervals, evidence, and findings.  It
does not read files, match identities, alter evidence, or create a report.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from aisc_imis.dated_membership import rule_date, select_first_join
from aisc_imis.evidence_ledger import (
    CandidateLifecycleEvent,
    InterpretationStatus,
    SnapshotStateObservation,
)
from aisc_imis.lifecycle_rules import (
    LifecycleObservation,
    LifecycleRules,
    evaluate_countability,
)
from aisc_imis.member_ledger import MemberLedgerEntry


class LifecycleState(StrEnum):
    """Reviewed operational states plus the explicit non-guessing state."""

    CURRENT_MEMBER = "current_member"
    FORMER_MEMBER = "former_member"
    POTENTIAL_MEMBER = "potential_member"
    UNKNOWN = "unknown"


class OpeningStrategy(StrEnum):
    """How reconstruction treats time before the first usable evidence."""

    UNKNOWN_BEFORE_COVERAGE = "unknown_before_coverage"


UNKNOWN_BEFORE_COVERAGE = OpeningStrategy.UNKNOWN_BEFORE_COVERAGE
"""Public name for the only opening strategy supported by this service."""


@dataclass(frozen=True)
class ReconstructionFinding:
    """A reviewable reason that reconstruction did not infer a state."""

    code: str
    message: str
    supporting_evidence: tuple[MemberLedgerEntry, ...] = ()


@dataclass(frozen=True)
class StateInterval:
    """An inclusive-start, exclusive-end span reconstructed from evidence."""

    start_date: date
    end_date: date | None
    state: LifecycleState
    supporting_evidence: tuple[MemberLedgerEntry, ...]


@dataclass(frozen=True)
class LifecycleReconstruction:
    """State as of a date, its history, all used evidence, and findings."""

    subject_key: str
    as_of_date: date
    state: LifecycleState
    intervals: tuple[StateInterval, ...]
    supporting_evidence: tuple[MemberLedgerEntry, ...]
    findings: tuple[ReconstructionFinding, ...]
    opening_strategy: OpeningStrategy = UNKNOWN_BEFORE_COVERAGE


@dataclass(frozen=True)
class _StatePoint:
    when: date
    state: LifecycleState | None
    evidence: tuple[MemberLedgerEntry, ...]
    findings: tuple[ReconstructionFinding, ...]


def reconstruct_member_lifecycle(
    entries: Iterable[MemberLedgerEntry],
    as_of_date: date,
    rules: LifecycleRules,
    knowledge_cutoff: date | None = None,
) -> LifecycleReconstruction:
    """Reconstruct one confirmed member's state as of ``as_of_date``.

    Evidence is considered only when it both applies by the requested date and
    was recorded or observed by that date.  Before the first usable point the
    state is always unknown.  Same-day competing states remain in the result
    and produce an unknown interval instead of an arbitrary ordering.
    """
    evidence = tuple(entries)
    cutoff = knowledge_cutoff or as_of_date
    subject_keys = {entry.record.subject_key for entry in evidence}
    if len(subject_keys) > 1:
        raise ValueError("Reconstruction accepts evidence for exactly one subject_key.")
    subject_key = next(iter(subject_keys), "")
    findings: list[ReconstructionFinding] = []
    has_unplaced_unknown = False
    latest_unplaced_date: date | None = None
    points_by_date: dict[date, list[_StatePoint]] = defaultdict(list)
    retained: list[MemberLedgerEntry] = []

    snapshot_groups: dict[tuple[object, ...], list[MemberLedgerEntry]] = defaultdict(list)
    for entry in evidence:
        record = entry.record
        if isinstance(record, SnapshotStateObservation):
            snapshot_groups[_snapshot_key(entry)].append(entry)
        elif isinstance(record, CandidateLifecycleEvent):
            if record.effective_date is None and _known_by(
                record.recorded_date, record.observed_date, cutoff
            ):
                has_unplaced_unknown = True
                latest_unplaced_date = max(latest_unplaced_date or date.min, _calendar_date(record.recorded_date) or _calendar_date(record.observed_date) or date.min)
                findings.append(_missing_date_finding(entry, "event"))
            point = _event_point(entry, as_of_date, rules, cutoff)
            if point is not None:
                points_by_date[point.when].append(point)
                retained.extend(point.evidence)
                findings.extend(point.findings)

    for group in snapshot_groups.values():
        first_record = group[0].record
        assert isinstance(first_record, SnapshotStateObservation)
        if (
            first_record.effective_date is None
            and first_record.observed_date is None
            and _known_by(first_record.recorded_date, None, cutoff)
        ):
            has_unplaced_unknown = True
            findings.append(_missing_date_finding(group[0], "snapshot"))
        point = _snapshot_point(tuple(group), as_of_date, rules, cutoff)
        if point is not None:
            points_by_date[point.when].append(point)
            retained.extend(point.evidence)
            findings.extend(point.findings)

    selection = select_first_join(evidence, rules, cutoff)
    findings.extend(ReconstructionFinding(code, "Join Date needs review.", selection.evidence) for code in selection.findings)
    if selection.effective_date is not None and selection.effective_date <= as_of_date:
        points_by_date[selection.effective_date].append(_StatePoint(selection.effective_date, LifecycleState.CURRENT_MEMBER, selection.evidence, ()))
        retained.extend(selection.evidence)

    intervals: list[StateInterval] = []
    current_state = LifecycleState.UNKNOWN
    current_start: date | None = None
    current_evidence: tuple[MemberLedgerEntry, ...] = ()
    for when in sorted(points_by_date):
        point_state, point_evidence, point_findings = _resolve_day(points_by_date[when])
        findings.extend(point_findings)
        state = point_state or LifecycleState.UNKNOWN
        if current_start is None:
            current_start, current_state, current_evidence = when, state, point_evidence
        elif state == current_state:
            current_evidence += point_evidence
        else:
            if (current_state is LifecycleState.CURRENT_MEMBER
                and state is LifecycleState.FORMER_MEMBER
                and all(isinstance(item.record, SnapshotStateObservation) for item in point_evidence)):
                findings.append(ReconstructionFinding("undated_snapshot_change", "The snapshot confirms former status but does not date the exit.", point_evidence))
            intervals.append(
                StateInterval(current_start, when, current_state, current_evidence)
            )
            current_start, current_state, current_evidence = when, state, point_evidence

    if current_start is not None:
        intervals.append(StateInterval(current_start, None, current_state, current_evidence))

    result_state = (
        LifecycleState.UNKNOWN
        if current_start is None or (has_unplaced_unknown and (latest_unplaced_date or date.min) > current_start)
        else current_state
    )
    return LifecycleReconstruction(
        subject_key=subject_key,
        as_of_date=as_of_date,
        state=result_state,
        intervals=tuple(intervals),
        supporting_evidence=tuple(retained),
        findings=tuple(findings),
    )


def _event_point(
    entry: MemberLedgerEntry, as_of_date: date, rules: LifecycleRules, cutoff: date
) -> _StatePoint | None:
    record = entry.record
    assert isinstance(record, CandidateLifecycleEvent)
    when = _calendar_date(record.effective_date)
    if when is None:
        return _missing_date_point(entry, as_of_date, "event")
    if not _usable_by(record.recorded_date, record.observed_date, when, as_of_date, cutoff):
        return None
    if record.interpretation_status in {
        InterpretationStatus.AMBIGUOUS,
        InterpretationStatus.UNRESOLVED,
    }:
        return _unknown_point(when, entry, "unresolved_lifecycle_evidence")
    decision = evaluate_countability(LifecycleObservation(event_name=record.event_name), rule_date(when, rules), rules)
    findings = tuple(
        ReconstructionFinding(finding.code, finding.message, (entry,))
        for finding in decision.findings
    )
    return _StatePoint(
        when,
        _as_state(decision.event_target_state),
        (entry,),
        findings,
    )


def _snapshot_point(
    entries: tuple[MemberLedgerEntry, ...], as_of_date: date, rules: LifecycleRules, cutoff: date
) -> _StatePoint | None:
    first = entries[0].record
    assert isinstance(first, SnapshotStateObservation)
    when = _calendar_date(first.effective_date) or _calendar_date(first.observed_date)
    if when is None:
        return _missing_date_point(entries[0], as_of_date, "snapshot")
    if not _usable_by(first.observed_date or first.recorded_date, None, when, as_of_date, cutoff):
        return None
    if any(
        entry.record.interpretation_status
        in {InterpretationStatus.AMBIGUOUS, InterpretationStatus.UNRESOLVED}
        for entry in entries
    ):
        return _unknown_point(when, entries, "unresolved_lifecycle_evidence")
    values = _snapshot_values(entries)
    if values is None:
        return _unknown_point(when, entries, "invalid_snapshot_field")
    decision = evaluate_countability(LifecycleObservation(**values), rule_date(when, rules), rules)
    findings = tuple(
        ReconstructionFinding(finding.code, finding.message, entries)
        for finding in decision.findings
    )
    return _StatePoint(when, _as_state(decision.operational_state), entries, findings)


def _resolve_day(
    points: list[_StatePoint],
) -> tuple[LifecycleState | None, tuple[MemberLedgerEntry, ...], tuple[ReconstructionFinding, ...]]:
    evidence = tuple(entry for point in points for entry in point.evidence)
    findings = tuple(finding for point in points for finding in point.findings)
    states = {point.state for point in points if point.state is not None}
    if len(states) == 1 and all(point.state is not None for point in points):
        return states.pop(), evidence, findings
    if len(states) > 1:
        contradiction = ReconstructionFinding(
            "same_day_state_contradiction",
            "Conflicting lifecycle evidence applies on the same day.",
            evidence,
        )
        return None, evidence, (*findings, contradiction)
    return None, evidence, findings


def _snapshot_key(entry: MemberLedgerEntry) -> tuple[object, ...]:
    record = entry.record
    assert isinstance(record, SnapshotStateObservation)
    return (
        record.source_reference,
        record.effective_date,
        record.recorded_date,
        record.observed_date,
    )


def _snapshot_values(entries: tuple[MemberLedgerEntry, ...]) -> dict[str, object] | None:
    values: dict[str, object] = {}
    allowed = {"member_type", "is_company", "is_member", "category", "status"}
    for entry in entries:
        record = entry.record
        assert isinstance(record, SnapshotStateObservation)
        if "=" not in record.state_name:
            return None
        field, value = record.state_name.split("=", 1)
        if field not in allowed or field in values:
            return None
        if field in {"is_company", "is_member"}:
            if value not in {"True", "False", "true", "false"}:
                return None
            values[field] = value.lower() == "true"
        else:
            values[field] = value
    return values


def _missing_date_point(
    entry: MemberLedgerEntry, as_of_date: date, kind: str
) -> _StatePoint | None:
    record = entry.record
    if not _known_by(record.recorded_date, record.observed_date, as_of_date):
        return None
    # A date-less record cannot be placed in history.  Returning no point still
    # leaves the result unknown unless other usable evidence covers the request.
    return None


def _missing_date_finding(entry: MemberLedgerEntry, kind: str) -> ReconstructionFinding:
    return ReconstructionFinding(
        "missing_lifecycle_date",
        f"{kind.capitalize()} evidence has no usable date for reconstruction.",
        (entry,),
    )


def _unknown_point(
    when: date,
    evidence: MemberLedgerEntry | tuple[MemberLedgerEntry, ...],
    code: str,
) -> _StatePoint:
    entries = evidence if isinstance(evidence, tuple) else (evidence,)
    return _StatePoint(
        when,
        None,
        entries,
        (ReconstructionFinding(code, "Lifecycle evidence needs review.", entries),),
    )


def _usable_by(
    recorded: date | datetime | None,
    observed: date | datetime | None,
    applies: date,
    as_of_date: date,
    cutoff: date,
) -> bool:
    return applies <= as_of_date and _known_by(recorded, observed, cutoff)


def _known_by(
    recorded: date | datetime | None,
    observed: date | datetime | None,
    as_of_date: date,
) -> bool:
    available = _calendar_date(recorded) or _calendar_date(observed)
    return available is not None and available <= as_of_date


def _calendar_date(value: date | datetime | None) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value


def _as_state(value: str | None) -> LifecycleState | None:
    if value in {None, "", "none"}:
        return None
    try:
        return LifecycleState(value)
    except ValueError:
        return None


reconstruct_lifecycle_state = reconstruct_member_lifecycle
"""Short alias for :func:`reconstruct_member_lifecycle`."""
