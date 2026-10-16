"""Dated, source-backed member state used by reconciliation comparisons."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from aisc_imis.evidence_ledger import CandidateLifecycleEvent, SnapshotStateObservation
from aisc_imis.lifecycle_rules import (
    Countability,
    LifecycleObservation,
    LifecycleRules,
    evaluate_countability,
)
from aisc_imis.member_ledger import MemberLedgerEntry

FIELDS = ("member_type", "status", "is_company", "is_member", "category")
COUNT_FIELDS = ("member_type", "is_company", "is_member")


@dataclass(frozen=True)
class FieldState:
    """One supported value, or an unknown value with its relevant evidence."""

    value: str | bool | Countability | None = None
    evidence: tuple[MemberLedgerEntry, ...] = ()
    reason: str | None = None


@dataclass(frozen=True)
class StateIssue:
    code: str
    field: str
    evidence: tuple[MemberLedgerEntry, ...]


@dataclass(frozen=True)
class MemberState:
    fields: dict[str, FieldState]
    countability: FieldState
    issues: tuple[StateIssue, ...]

    def field(self, name: str) -> FieldState:
        return self.fields[name]


@dataclass(frozen=True)
class _Point:
    applies: date
    known: date
    entry: MemberLedgerEntry
    field: str | None
    value: str | bool | None
    event_target: Countability | None
    unresolved: bool = False


class MemberStateHistory:
    """One chronological evidence index for an already confirmed member.

    A comparison reads only points that applied and were known before its date.
    Results are cached by date, so rows from the same export share one replay.
    """

    def __init__(self, entries: tuple[MemberLedgerEntry, ...], rules: LifecycleRules):
        self.rules = rules
        self.points: list[_Point] = []
        self._cache: dict[date, MemberState] = {}
        for entry in entries:
            record = entry.record
            applies = day(record.effective_date) or day(record.observed_date)
            known_dates = tuple(
                value
                for value in (day(record.recorded_date), day(record.observed_date))
                if value is not None
            )
            known = max(known_dates) if known_dates else None
            if applies is None or known is None:
                continue
            unresolved = record.interpretation_status in {"ambiguous", "unresolved"}
            if isinstance(record, SnapshotStateObservation):
                field, separator, raw = record.state_name.partition("=")
                if not separator or field not in FIELDS:
                    continue
                value: str | bool = raw
                if field in {"is_company", "is_member"}:
                    if raw.lower() not in {"true", "false"}:
                        continue
                    value = raw.lower() == "true"
                self.points.append(
                    _Point(applies, known, entry, field, value, None, unresolved)
                )
            elif isinstance(record, CandidateLifecycleEvent):
                decision = evaluate_countability(
                    LifecycleObservation(event_name=record.event_name), applies, rules
                )
                target = {
                    "current_member": Countability.COUNTABLE,
                    "former_member": Countability.NOT_COUNTABLE,
                    "potential_member": Countability.NOT_COUNTABLE,
                }.get(decision.event_target_state)
                if target is None:
                    continue
                self.points.append(
                    _Point(applies, known, entry, None, None, target, unresolved)
                )
                if record.member_type is not None:
                    self.points.append(
                        _Point(
                            applies,
                            known,
                            entry,
                            "member_type",
                            record.member_type,
                            None,
                            unresolved,
                        )
                    )
                if record.category is not None:
                    self.points.append(
                        _Point(
                            applies,
                            known,
                            entry,
                            "category",
                            record.category,
                            None,
                            unresolved,
                        )
                    )
        self.points.sort(
            key=lambda point: (point.applies, point.entry.record_id, point.field or "")
        )

    def state_before(self, when: date) -> MemberState:
        if when not in self._cache:
            self._cache[when] = self._replay(when)
        return self._cache[when]

    def _replay(self, when: date) -> MemberState:
        fields = {name: FieldState() for name in FIELDS}
        count = FieldState()
        issues: list[StateIssue] = []
        by_day: dict[date, list[_Point]] = defaultdict(list)
        for point in self.points:
            if point.applies > when:
                break
            if point.known <= when and (
                point.applies < when
                or isinstance(point.entry.record, CandidateLifecycleEvent)
            ):
                by_day[point.applies].append(point)
        event_active = False
        for applied in sorted(by_day):
            points = by_day[applied]
            for field in FIELDS:
                candidates = [point for point in points if point.field == field]
                if not candidates:
                    continue
                evidence = unique(point.entry for point in candidates)
                values = {point.value for point in candidates if not point.unresolved}
                if any(point.unresolved for point in candidates):
                    fields[field] = FieldState(
                        None, evidence, "unresolved_lifecycle_evidence"
                    )
                    issues.append(
                        StateIssue("unresolved_lifecycle_evidence", field, evidence)
                    )
                elif len(values) > 1:
                    fields[field] = FieldState(
                        None, evidence, "snapshot_state_conflict"
                    )
                    issues.append(
                        StateIssue("snapshot_state_conflict", field, evidence)
                    )
                else:
                    fields[field] = FieldState(next(iter(values)), evidence)
            event_points = [point for point in points if point.event_target is not None]
            snapshot_points = [
                point
                for point in points
                if isinstance(point.entry.record, SnapshotStateObservation)
            ]
            snapshots_by_row: dict[object, set[str]] = defaultdict(set)
            for point in snapshot_points:
                snapshots_by_row[point.entry.record.source_reference].add(
                    point.field or ""
                )
            complete_snapshot = any(
                set(COUNT_FIELDS) <= names for names in snapshots_by_row.values()
            )
            count_candidates: list[FieldState] = []
            if event_points:
                evidence = unique(point.entry for point in event_points)
                values = {
                    point.event_target for point in event_points if not point.unresolved
                }
                if any(point.unresolved for point in event_points):
                    count_candidates.append(
                        FieldState(None, evidence, "unresolved_lifecycle_evidence")
                    )
                    issues.append(
                        StateIssue(
                            "unresolved_lifecycle_evidence", "countability", evidence
                        )
                    )
                elif len(values) > 1:
                    count_candidates.append(
                        FieldState(None, evidence, "same_day_state_contradiction")
                    )
                    issues.append(
                        StateIssue(
                            "same_day_state_contradiction", "countability", evidence
                        )
                    )
                else:
                    count_candidates.append(FieldState(next(iter(values)), evidence))
            if snapshot_points and (complete_snapshot or not event_active):
                support = unique(
                    entry for field in COUNT_FIELDS for entry in fields[field].evidence
                )
                if all(fields[field].value is not None for field in COUNT_FIELDS):
                    decision = evaluate_countability(
                        LifecycleObservation(
                            member_type=str(fields["member_type"].value),
                            is_company=bool(fields["is_company"].value),
                            is_member=bool(fields["is_member"].value),
                            category=(
                                str(fields["category"].value)
                                if fields["category"].value is not None
                                else None
                            ),
                        ),
                        when,
                        self.rules,
                    )
                    value = decision.countability
                    count_candidates.append(
                        FieldState(
                            value if value != Countability.UNKNOWN else None,
                            support,
                            "unassessable_countability_snapshot"
                            if value == Countability.UNKNOWN
                            else None,
                        )
                    )
                else:
                    count_candidates.append(
                        FieldState(None, support, "unassessable_countability_snapshot")
                    )
            if count_candidates:
                values = {candidate.value for candidate in count_candidates}
                evidence = unique(
                    entry
                    for candidate in count_candidates
                    for entry in candidate.evidence
                )
                if len(values) > 1:
                    count = FieldState(None, evidence, "same_day_state_contradiction")
                    issues.append(
                        StateIssue(
                            "same_day_state_contradiction", "countability", evidence
                        )
                    )
                else:
                    count = FieldState(
                        next(iter(values)),
                        evidence,
                        next(
                            (
                                candidate.reason
                                for candidate in count_candidates
                                if candidate.reason
                            ),
                            None,
                        ),
                    )
                if event_points:
                    event_active = not complete_snapshot or count.reason is not None
                elif complete_snapshot:
                    event_active = False
        return MemberState(fields, count, tuple(issues))


def day(value: date | datetime | None) -> date | None:
    return value.date() if isinstance(value, datetime) else value


def unique(entries) -> tuple[MemberLedgerEntry, ...]:
    return tuple(
        sorted(
            {entry.record_id: entry for entry in entries}.values(),
            key=lambda entry: entry.record_id,
        )
    )
