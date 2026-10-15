"""Conservative period movement analysis for confirmed member-ledger evidence.

The analysis is deliberately a pure service.  It accepts immutable ledger
entries and explicit corrections; it never edits a ledger or guesses an
unknown starting position.  A period is ``[start_date, end_date)``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime

from aisc_imis.evidence_ledger import (
    CandidateLifecycleEvent,
    InterpretationStatus,
    SnapshotStateObservation,
)
from aisc_imis.lifecycle_rules import (
    Countability,
    LifecycleObservation,
    LifecycleRules,
    evaluate_countability,
)
from aisc_imis.member_ledger import MemberLedgerEntry
from aisc_imis.normalization_contracts import SourceReference


@dataclass(frozen=True)
class EvidenceCorrection:
    """An auditable instruction to use one ledger record in place of another.

    Both record IDs continue to exist in the ledger.  The correction is only
    applied to the reconstruction or analysis call which receives it.
    """

    subject_key: str
    superseded_record_id: str
    replacement_record_id: str
    source_references: tuple[SourceReference, ...]
    reason: str
    effective_date: date | datetime | None = None
    recorded_date: date | datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_references", tuple(self.source_references))
        if not self.subject_key.strip() or not self.superseded_record_id.strip() or not self.replacement_record_id.strip() or not self.reason.strip():
            raise ValueError("Correction subject, record IDs, and reason must be nonblank.")
        if not self.source_references:
            raise ValueError("Corrections require at least one source reference.")


# A shorter name is convenient for callers while retaining the explicit model name.
LedgerCorrection = EvidenceCorrection


@dataclass(frozen=True)
class MovementFinding:
    code: str
    message: str
    supporting_evidence: tuple[MemberLedgerEntry, ...] = ()


@dataclass(frozen=True)
class DimensionTransfer:
    dimension: str
    outgoing: str
    incoming: str
    effective_date: date
    supporting_evidence: tuple[MemberLedgerEntry, ...]


@dataclass(frozen=True)
class MemberMovementContributor:
    subject_key: str
    opening_countability: Countability
    closing_countability: Countability
    lifecycle_actions: tuple[str, ...]
    membership_grouping_transfers: tuple[DimensionTransfer, ...]
    category_transfers: tuple[DimensionTransfer, ...]
    supporting_evidence: tuple[MemberLedgerEntry, ...]
    findings: tuple[MovementFinding, ...]


@dataclass(frozen=True)
class PeriodMembershipMovementAnalysis:
    """Structured, aggregate-safe result of one inclusive/exclusive period."""

    start_date: date
    end_date: date
    contributors: tuple[MemberMovementContributor, ...]
    gross_lifecycle_actions: dict[str, int]
    net_population_change: int | None
    membership_grouping_transfers: tuple[DimensionTransfer, ...]
    category_transfers: tuple[DimensionTransfer, ...]
    applied_corrections: tuple[EvidenceCorrection, ...]
    supporting_evidence: tuple[MemberLedgerEntry, ...]
    findings: tuple[MovementFinding, ...]


@dataclass(frozen=True)
class _Profile:
    countability: Countability
    member_type: str | None
    category: str | None


@dataclass(frozen=True)
class _Point:
    when: date
    profile: _Profile | None
    event_name: str | None
    entry: MemberLedgerEntry


def analyze_period_membership_movements(
    entries: Iterable[MemberLedgerEntry],
    start_date: date,
    end_date: date,
    rules: LifecycleRules,
    corrections: Iterable[EvidenceCorrection] = (),
) -> PeriodMembershipMovementAnalysis:
    """Analyze confirmed evidence over ``[start_date, end_date)``.

    Countable-to-countable changes create separate outgoing/incoming movement
    records for Member Type (called membership grouping in reports) and
    Category.  No transfer changes total population.  Unknown or contradictory
    evidence produces findings instead of a guessed movement.
    """
    if end_date <= start_date:
        raise ValueError("end_date must be after start_date.")
    original = tuple(entries)
    retained, applied, correction_findings = _apply_corrections(original, tuple(corrections))
    by_subject: dict[str, list[MemberLedgerEntry]] = defaultdict(list)
    for entry in retained:
        by_subject[entry.record.subject_key].append(entry)

    contributors: list[MemberMovementContributor] = []
    all_grouping: list[DimensionTransfer] = []
    all_category: list[DimensionTransfer] = []
    all_findings = list(correction_findings)
    gross: dict[str, int] = defaultdict(int)
    net_changes: list[int] = []
    for subject_key, subject_entries in sorted(by_subject.items()):
        contributor = _analyze_member(subject_key, tuple(subject_entries), start_date, end_date, rules)
        contributors.append(contributor)
        all_grouping.extend(contributor.membership_grouping_transfers)
        all_category.extend(contributor.category_transfers)
        all_findings.extend(contributor.findings)
        for action in contributor.lifecycle_actions:
            gross[action] += 1
        if contributor.opening_countability is Countability.UNKNOWN or contributor.closing_countability is Countability.UNKNOWN:
            continue
        net_changes.append(
            int(contributor.closing_countability is Countability.COUNTABLE)
            - int(contributor.opening_countability is Countability.COUNTABLE)
        )
    net = sum(net_changes) if len(net_changes) == len(contributors) else None
    return PeriodMembershipMovementAnalysis(
        start_date, end_date, tuple(contributors), dict(sorted(gross.items())), net,
        tuple(all_grouping), tuple(all_category), applied, retained, tuple(all_findings)
    )


def _apply_corrections(entries: tuple[MemberLedgerEntry, ...], corrections: tuple[EvidenceCorrection, ...]) -> tuple[tuple[MemberLedgerEntry, ...], tuple[EvidenceCorrection, ...], tuple[MovementFinding, ...]]:
    records = {entry.record_id: entry for entry in entries}
    replacement_links = {
        correction.superseded_record_id: correction.replacement_record_id
        for correction in corrections
    }
    superseded: set[str] = set()
    applied: list[EvidenceCorrection] = []
    findings: list[MovementFinding] = []
    for correction in corrections:
        old = records.get(correction.superseded_record_id)
        new = records.get(correction.replacement_record_id)
        if old is None or new is None or old.record.subject_key != correction.subject_key or new.record.subject_key != correction.subject_key:
            findings.append(MovementFinding("invalid_correction", "Correction IDs must identify records for its subject."))
        elif _has_correction_cycle(correction.superseded_record_id, replacement_links) or correction.superseded_record_id in superseded:
            findings.append(MovementFinding("cyclic_correction", "A correction cannot replace itself or an already superseded record."))
        else:
            superseded.add(correction.superseded_record_id)
            applied.append(correction)
    return tuple(entry for entry in entries if entry.record_id not in superseded), tuple(applied), tuple(findings)


def _has_correction_cycle(start: str, links: dict[str, str]) -> bool:
    seen: set[str] = set()
    current = start
    while current in links:
        if current in seen:
            return True
        seen.add(current)
        current = links[current]
    return False


def _analyze_member(subject_key: str, entries: tuple[MemberLedgerEntry, ...], start: date, end: date, rules: LifecycleRules) -> MemberMovementContributor:
    points, findings = _points(entries, end, rules)
    profile = _Profile(Countability.UNKNOWN, None, None)
    actions: list[str] = []
    grouping: list[DimensionTransfer] = []
    category: list[DimensionTransfer] = []
    used: list[MemberLedgerEntry] = []
    for when in sorted(points):
        day = points[when]
        candidates = [point.profile for point in day if point.profile is not None]
        if len({candidate for candidate in candidates}) > 1:
            findings.append(MovementFinding("same_day_state_contradiction", "Conflicting evidence applies on the same day.", tuple(point.entry for point in day)))
            profile = _Profile(Countability.UNKNOWN, None, None)
            continue
        if not candidates:
            continue
        point = next(item for item in day if item.profile is not None)
        next_profile = _merge(profile, point.profile)
        if when >= start:
            if point.event_name in {"joined", "reinstated", "resigned", "expelled"}:
                if profile.countability is Countability.UNKNOWN:
                    findings.append(MovementFinding("unknown_starting_state", "A lifecycle event cannot be counted without a known preceding state.", (point.entry,)))
                elif next_profile.countability == profile.countability:
                    findings.append(MovementFinding("repeated_lifecycle_event", "The event cannot represent a state change.", (point.entry,)))
                else:
                    actions.append(point.event_name)
            _transfers(profile, next_profile, when, point.entry, grouping, category)
        profile = next_profile
        used.extend(item.entry for item in day)
    opening = _profile_at(points, start, rules, entries)
    closing = profile
    if opening.countability is Countability.UNKNOWN:
        findings.append(MovementFinding("unknown_starting_state", "No confirmed countability state covers the period start."))
    return MemberMovementContributor(subject_key, opening.countability, closing.countability, tuple(actions), tuple(grouping), tuple(category), tuple(used), tuple(findings))


def _profile_at(points: dict[date, list[_Point]], at: date, rules: LifecycleRules, entries: tuple[MemberLedgerEntry, ...]) -> _Profile:
    profile = _Profile(Countability.UNKNOWN, None, None)
    for when in sorted(day for day in points if day < at):
        candidates = [point.profile for point in points[when] if point.profile is not None]
        if len(set(candidates)) != 1:
            return _Profile(Countability.UNKNOWN, None, None)
        profile = _merge(profile, candidates[0])
    return profile


def _points(entries: tuple[MemberLedgerEntry, ...], end: date, rules: LifecycleRules) -> tuple[dict[date, list[_Point]], list[MovementFinding]]:
    output: dict[date, list[_Point]] = defaultdict(list)
    findings: list[MovementFinding] = []
    snapshot_groups: dict[tuple[object, ...], list[MemberLedgerEntry]] = defaultdict(list)
    for entry in entries:
        record = entry.record
        if isinstance(record, SnapshotStateObservation):
            snapshot_groups[(record.source_reference, record.effective_date, record.recorded_date, record.observed_date)].append(entry)
        elif isinstance(record, CandidateLifecycleEvent):
            when = _day(record.effective_date)
            if when is None or when >= end or not _known(record.recorded_date, record.observed_date, end):
                continue
            if record.interpretation_status in {InterpretationStatus.AMBIGUOUS, InterpretationStatus.UNRESOLVED}:
                findings.append(MovementFinding("unresolved_lifecycle_evidence", "Lifecycle evidence needs review.", (entry,)))
                continue
            decision = evaluate_countability(LifecycleObservation(event_name=record.event_name), when, rules)
            if decision.event_target_state in {None, "", "none"} and record.event_name != "transferred":
                findings.append(MovementFinding("unresolved_lifecycle_evidence", "Lifecycle event has no approved transition.", (entry,)))
                continue
            target = _event_target_countability(record.event_name)
            output[when].append(_Point(when, _Profile(target or Countability.UNKNOWN, record.member_type, record.category), record.event_name, entry))
    for grouped in snapshot_groups.values():
        record = grouped[0].record
        assert isinstance(record, SnapshotStateObservation)
        when = _day(record.effective_date) or _day(record.observed_date)
        if when is None or when >= end or not _known(record.recorded_date, record.observed_date, end):
            continue
        values = _snapshot_values(grouped)
        if values is None:
            findings.append(MovementFinding("invalid_snapshot_field", "Snapshot state fields are invalid or incomplete.", tuple(grouped)))
            continue
        decision = evaluate_countability(LifecycleObservation(**values), when, rules)
        if decision.countability is Countability.UNKNOWN:
            findings.append(MovementFinding("unresolved_lifecycle_evidence", "Snapshot evidence has no approved countability state.", tuple(grouped)))
            continue
        output[when].append(_Point(when, _Profile(decision.countability, values.get("member_type"), values.get("category")), None, grouped[0]))
    return output, findings


def _snapshot_values(entries: list[MemberLedgerEntry]) -> dict[str, object] | None:
    values: dict[str, object] = {}
    for entry in entries:
        record = entry.record
        assert isinstance(record, SnapshotStateObservation)
        if "=" not in record.state_name:
            return None
        field, value = record.state_name.split("=", 1)
        if field in values or field not in {"member_type", "category", "is_company", "is_member", "status"}:
            return None
        values[field] = value.lower() == "true" if field in {"is_company", "is_member"} and value.lower() in {"true", "false"} else value
    return values


def _merge(old: _Profile, new: _Profile) -> _Profile:
    return _Profile(new.countability if new.countability is not Countability.UNKNOWN else old.countability, new.member_type or old.member_type, new.category or old.category)


def _event_target_countability(event_name: str) -> Countability:
    if event_name in {"joined", "reinstated"}:
        return Countability.COUNTABLE
    if event_name in {"resigned", "expelled"}:
        return Countability.NOT_COUNTABLE
    return Countability.UNKNOWN


def _transfers(old: _Profile, new: _Profile, when: date, entry: MemberLedgerEntry, grouping: list[DimensionTransfer], category: list[DimensionTransfer]) -> None:
    if old.countability is not Countability.COUNTABLE or new.countability is not Countability.COUNTABLE:
        return
    if old.member_type and new.member_type and old.member_type != new.member_type:
        grouping.append(DimensionTransfer("membership_grouping", old.member_type, new.member_type, when, (entry,)))
    if old.category and new.category and old.category != new.category:
        category.append(DimensionTransfer("category", old.category, new.category, when, (entry,)))


def _day(value: date | datetime | None) -> date | None:
    return value.date() if isinstance(value, datetime) else value


def _known(recorded: date | datetime | None, observed: date | datetime | None, end: date) -> bool:
    return any(day is not None and day < end for day in (_day(recorded), _day(observed)))
