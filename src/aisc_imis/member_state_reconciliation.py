"""Compare membership observations with evidence available independently of that date.

The caller has already confirmed subject keys. This module neither links people
nor treats an unexplained change as proof that any source row is wrong.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime

from aisc_imis.current_member_records import CurrentMemberObservation
from aisc_imis.evidence_ledger import (
    CandidateLifecycleEvent,
    ObservedFact,
    SnapshotStateObservation,
)
from aisc_imis.finding_taxonomy import (
    ReconciliationFinding,
    build_finding,
    order_findings,
)
from aisc_imis.historical_snapshot_records import HistoricalSnapshotObservation
from aisc_imis.lifecycle_rules import (
    Countability,
    LifecycleObservation,
    LifecycleRules,
    evaluate_countability,
)
from aisc_imis.member_ledger import (
    MemberEvidenceLedger,
    MemberLedgerEntry,
    build_member_evidence_ledger,
)
from aisc_imis.normalization_contracts import SourceReference


@dataclass(frozen=True)
class MembershipObservation:
    """A normalized historical or current row; ``None`` means unknown."""

    subject_key: str
    source_reference: SourceReference
    observation_date: date | None = None
    member_type: str | None = None
    status: str | None = None
    is_company: bool | None = None
    is_member: bool | None = None
    category: str | None = None

    @classmethod
    def from_historical(
        cls, row: HistoricalSnapshotObservation
    ) -> MembershipObservation:
        """Use an accepted historical adapter row and its configured date."""
        return cls(
            row.imis_id,
            row.record.reference,
            row.observation_date,
            row.member_type,
            row.status,
            row.is_company,
            row.is_member,
            row.category,
        )

    @classmethod
    def from_current(cls, row: CurrentMemberObservation) -> MembershipObservation:
        """Use an accepted current adapter row; the caller supplies export date."""
        return cls(
            row.imis_id,
            row.record.reference,
            None,
            row.member_type,
            row.status,
            row.is_company,
            row.is_member,
            row.category,
        )


@dataclass(frozen=True)
class MembershipComparison:
    """One observed row and what independent evidence can support at its date."""

    observation: MembershipObservation
    comparison_date: date | None
    outcome: str  # match, discrepancy, or unassessable
    expected_member_type: str | None
    expected_status: str | None
    expected_countability: Countability | None
    observed_countability: Countability | None
    supporting_evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class MemberStateReconciliation:
    comparisons: tuple[MembershipComparison, ...]
    findings: tuple[ReconciliationFinding, ...]


def reconcile_member_states(
    evidence: MemberEvidenceLedger,
    historical_observations: Iterable[MembershipObservation],
    current_observations: Iterable[MembershipObservation],
    rules: LifecycleRules,
    *,
    current_export_date: date,
) -> MemberStateReconciliation:
    """Compare every row with earlier rows and applicable reviewed events.

    All snapshots on the comparison date are withheld from that date's
    baseline, including snapshots supplied in ``evidence``. Current rows use
    ``current_export_date``; historical rows use their configured date.
    """
    historical = tuple(historical_observations)
    current = tuple(current_observations)
    dated = tuple((item, item.observation_date) for item in historical) + tuple(
        (item, current_export_date) for item in current
    )
    records = [entry.record for entry in evidence.entries]
    for item, when in dated:
        if not item.subject_key.strip():
            raise ValueError("Observation subject_key must be nonblank.")
        records.extend(_as_snapshot_records(item, when))
    ledger = build_member_evidence_ledger(records)
    # Identical records can arrive both in the confirmed ledger and as supplied
    # observations. Keep one copy for comparison and stable evidence citations.
    entries = tuple({entry.record_id: entry for entry in ledger.entries}.values())
    entries = tuple(sorted(entries, key=lambda entry: entry.record_id))
    snapshots: dict[tuple[str, date], list[MemberLedgerEntry]] = defaultdict(list)
    field_snapshots: dict[tuple[str, str, date], list[MemberLedgerEntry]] = (
        defaultdict(list)
    )
    snapshot_days: dict[str, set[date]] = defaultdict(set)
    count_snapshot_days: dict[str, set[date]] = defaultdict(set)
    field_days: dict[tuple[str, str], set[date]] = defaultdict(set)
    events_by_subject: dict[str, list[tuple[date, MemberLedgerEntry]]] = (
        defaultdict(list)
    )
    target_index: dict[
        tuple[str, SourceReference, date | None], list[MemberLedgerEntry]
    ] = defaultdict(list)
    for entry in entries:
        record = entry.record
        if isinstance(record, (SnapshotStateObservation, ObservedFact)):
            target_index[
                record.subject_key, record.source_reference, _day(record.observed_date)
            ].append(entry)
        if isinstance(record, SnapshotStateObservation):
            day = _snapshot_day(entry)
            if day is not None:
                snapshots[record.subject_key, day].append(entry)
                snapshot_days[record.subject_key].add(day)
                field, separator, _ = record.state_name.partition("=")
                if separator:
                    field_snapshots[record.subject_key, field, day].append(entry)
                    field_days[record.subject_key, field].add(day)
                    if field in {"member_type", "is_company", "is_member", "category"}:
                        count_snapshot_days[record.subject_key].add(day)
        elif isinstance(record, CandidateLifecycleEvent):
            event_date = _day(record.effective_date)
            if event_date is not None:
                events_by_subject[record.subject_key].append((event_date, entry))
    ordered_snapshot_days = {
        subject: tuple(sorted(days)) for subject, days in snapshot_days.items()
    }
    ordered_count_days = {
        subject: tuple(sorted(days)) for subject, days in count_snapshot_days.items()
    }
    ordered_field_days = {
        key: tuple(sorted(days)) for key, days in field_days.items()
    }
    ordered_events = {
        subject: tuple(
            sorted(
                group,
                key=lambda pair: (pair[0], pair[1].record_id),
            )
        )
        for subject, group in events_by_subject.items()
    }
    event_days = {
        subject: tuple(day for day, _ in group)
        for subject, group in ordered_events.items()
    }
    targets: dict[
        tuple[str, date],
        list[tuple[MembershipObservation, tuple[MemberLedgerEntry, ...]]],
    ] = defaultdict(list)
    for item, when in dated:
        if when is not None:
            target_entries = tuple(
                target_index.get((item.subject_key, item.source_reference, when), ())
            )
            targets[item.subject_key, when].append((item, target_entries))

    findings: list[ReconciliationFinding] = []
    for (subject, when), group in sorted(targets.items()):
        for field in ("member_type", "status", "is_company", "is_member", "category"):
            values = {
                getattr(item, field)
                for item, _ in group
                if getattr(item, field) is not None
            }
            if len(values) > 1:
                all_entries = tuple(entry for _, cited in group for entry in cited)
                findings.append(
                    build_finding(
                        "snapshot_state_conflict",
                        subject,
                        f"{when.isoformat()}:{field}",
                        supporting_evidence=all_entries,
                    )
                )

    comparisons: list[MembershipComparison] = []
    for item, when in sorted(
        dated,
        key=lambda pair: (
            pair[0].subject_key,
            pair[1] or date.min,
            pair[0].source_reference.source_name,
            pair[0].source_reference.row_reference,
        ),
    ):
        if when is None:
            undated = tuple(
                target_index.get((item.subject_key, item.source_reference, None), ())
            )
            findings.append(
                build_finding(
                    "missing_lifecycle_date",
                    item.subject_key,
                    f"undated:{item.source_reference.source_name}:{item.source_reference.row_reference}",
                    supporting_evidence=undated,
                )
            )
            comparisons.append(
                MembershipComparison(
                    item, None, "unassessable", None, None, None, None, ()
                )
            )
            continue
        target_entries = tuple(
            target_index.get((item.subject_key, item.source_reference, when), ())
        )
        latest_day = _latest_before(ordered_snapshot_days.get(item.subject_key, ()), when)
        prior = (
            tuple(snapshots.get((item.subject_key, latest_day), ()))
            if latest_day else ()
        )
        count_day = _latest_before(
            ordered_count_days.get(item.subject_key, ()), when
        )
        count_prior = (
            tuple(snapshots.get((item.subject_key, count_day), ()))
            if count_day else ()
        )
        type_day = _latest_before(
            ordered_field_days.get((item.subject_key, "member_type"), ()), when
        )
        status_day = _latest_before(
            ordered_field_days.get((item.subject_key, "status"), ()), when
        )
        type_support = (
            tuple(field_snapshots.get((item.subject_key, "member_type", type_day), ()))
            if type_day else ()
        )
        status_support = (
            tuple(field_snapshots.get((item.subject_key, "status", status_day), ()))
            if status_day else ()
        )
        # A Status-only snapshot cannot replace countability evidence.
        # Count events start after the latest snapshot with a count input.
        subject_events = ordered_events.get(item.subject_key, ())
        subject_event_days = event_days.get(item.subject_key, ())
        event_start = bisect_right(subject_event_days, type_day) if type_day else 0
        event_end = bisect_right(subject_event_days, when)
        applicable_events = tuple(
            entry
            for _, entry in subject_events[event_start:event_end]
            if (
                (
                    _day(entry.record.recorded_date)
                    or _day(entry.record.observed_date)
                    or date.max
                )
                <= when
                and _event_target(entry, when, rules) is not None
            )
        )
        intervening_events = tuple(
            entry
            for entry in applicable_events
            if (
                entry.record.member_type
                and (type_day is None or _day(entry.record.effective_date) > type_day)
            ) or (
                count_day is None or _day(entry.record.effective_date) > count_day
            )
        )
        unresolved = tuple(
            entry
            for entry in intervening_events
            if entry.record.interpretation_status in {"ambiguous", "unresolved"}
        )
        unresolved_ids = {entry.record_id for entry in unresolved}
        events = tuple(
            entry for entry in intervening_events
            if entry.record_id not in unresolved_ids
        )
        count_events = tuple(
            entry for entry in events
            if count_day is None or _day(entry.record.effective_date) > count_day
        )
        event_day = max(
            (_day(entry.record.effective_date) for entry in count_events), default=None
        )
        latest_events = tuple(
            entry
            for entry in count_events
            if _day(entry.record.effective_date) == event_day
        )
        expected_type = _single(_values(type_support)["member_type"])
        expected_status = _single(_values(status_support)["status"])
        count_support = count_prior
        # Only an event with an explicit Member Type can update that field.
        # Later events without one leave the last supported type in place.
        typed_events = tuple(
            entry for entry in events
            if entry.record.member_type
            and (type_day is None or _day(entry.record.effective_date) > type_day)
        )
        if typed_events:
            type_day = max(_day(entry.record.effective_date) for entry in typed_events)
            type_support = tuple(
                entry
                for entry in typed_events
                if _day(entry.record.effective_date) == type_day
            )
            expected_type = _single({entry.record.member_type for entry in type_support})
        if latest_events:
            count_support = latest_events

        observed_decision = evaluate_countability(_lifecycle(item), when, rules)
        observed_count = _known_count(observed_decision.countability)
        expected_count: Countability | None = None
        if observed_decision.rule_version is not None:
            if latest_events:
                states = {
                    evaluate_countability(
                        LifecycleObservation(event_name=entry.record.event_name),
                        when,
                        rules,
                    ).event_target_state
                    for entry in latest_events
                }
                if states == {"current_member"}:
                    expected_count = Countability.COUNTABLE
                elif states in ({"former_member"}, {"potential_member"}):
                    expected_count = Countability.NOT_COUNTABLE
            elif count_prior:
                expected_count = _count_from_prior(count_prior, when, rules)

        scope = f"{when.isoformat()}:{item.source_reference.source_name}:{item.source_reference.row_reference}"
        if (
            count_prior
            and not latest_events
            and not unresolved
            and expected_count is None
            and observed_count is not None
        ):
            findings.append(
                build_finding(
                    "unassessable_countability_snapshot",
                    item.subject_key,
                    f"{scope}:countability",
                    supporting_evidence=count_prior,
                    contradicting_evidence=target_entries,
                )
            )
        if unresolved:
            findings.append(
                build_finding(
                    "unresolved_lifecycle_evidence",
                    item.subject_key,
                    scope,
                    supporting_evidence=unresolved,
                    contradicting_evidence=target_entries,
                )
            )
            comparisons.append(
                MembershipComparison(
                    item,
                    when,
                    "unassessable",
                    None,
                    None,
                    None,
                    observed_count,
                    tuple(sorted({entry.record_id for entry in unresolved})),
                )
            )
            continue
        differences = []
        for field, expected, observed, field_support in (
            ("member_type", expected_type, item.member_type, type_support),
            ("status", expected_status, item.status, status_support),
        ):
            if expected is not None and observed is not None and expected != observed:
                differences.append(field)
                findings.append(
                    build_finding(
                        "possible_missing_transition",
                        item.subject_key,
                        f"{scope}:{field}",
                        supporting_evidence=field_support,
                        contradicting_evidence=target_entries,
                    )
                )
        if (
            expected_count is not None
            and observed_count is not None
            and expected_count != observed_count
        ):
            differences.append("countability")
            findings.append(
                build_finding(
                    "countability_difference",
                    item.subject_key,
                    f"{scope}:countability",
                    supporting_evidence=count_support,
                    contradicting_evidence=target_entries,
                )
            )
        if not prior and not latest_events:
            findings.append(
                build_finding(
                    "unknown_starting_state",
                    item.subject_key,
                    scope,
                    supporting_evidence=target_entries,
                )
            )
        assessable = any(
            (
                expected_type is not None and item.member_type is not None,
                expected_status is not None and item.status is not None,
                expected_count is not None and observed_count is not None,
            )
        )
        outcome = (
            "discrepancy" if differences else "match" if assessable else "unassessable"
        )
        comparisons.append(
            MembershipComparison(
                item,
                when,
                outcome,
                expected_type,
                expected_status,
                expected_count,
                observed_count,
                tuple(
                    sorted(
                        {
                            entry.record_id
                            for entry in (*type_support, *status_support, *count_support)
                        }
                    )
                ),
            )
        )
    return MemberStateReconciliation(tuple(comparisons), order_findings(findings))


def _as_snapshot_records(
    item: MembershipObservation, when: date | None
) -> tuple[ObservedFact | SnapshotStateObservation, ...]:
    anchor = ObservedFact(
        subject_key=item.subject_key,
        fact_name="observation_row",
        fact_value="present",
        source_reference=item.source_reference,
        observed_date=when,
    )
    fields = tuple(
        SnapshotStateObservation(
            subject_key=item.subject_key,
            state_name=f"{field}={value}",
            source_reference=item.source_reference,
            observed_date=when,
        )
        for field in ("member_type", "status", "is_company", "is_member", "category")
        if (value := getattr(item, field)) is not None
    )
    return (anchor, *fields)


def _day(value: date | datetime | None) -> date | None:
    return value.date() if isinstance(value, datetime) else value


def _snapshot_day(entry: MemberLedgerEntry) -> date | None:
    record = entry.record
    return _day(record.observed_date) or _day(record.effective_date)


def _latest_before(days: tuple[date, ...], when: date) -> date | None:
    position = bisect_left(days, when)
    return days[position - 1] if position else None


def _values(entries: tuple[MemberLedgerEntry, ...]) -> dict[str, set[object]]:
    values: dict[str, set[object]] = defaultdict(set)
    for entry in entries:
        record = entry.record
        field, separator, value = record.state_name.partition("=")
        if separator:
            values[field].add(value)
    return values


def _single(values: set[object]) -> str | None:
    return str(next(iter(values))) if len(values) == 1 else None


def _lifecycle(item: MembershipObservation) -> LifecycleObservation:
    return LifecycleObservation(
        item.member_type,
        item.is_company,
        item.is_member,
        item.category,
        status=item.status,
    )


def _known_count(value: Countability) -> Countability | None:
    return None if value == Countability.UNKNOWN else value


def _event_target(
    entry: MemberLedgerEntry, when: date, rules: LifecycleRules
) -> str | None:
    record = entry.record
    target = evaluate_countability(
        LifecycleObservation(event_name=record.event_name), when, rules
    ).event_target_state
    return None if target in {None, "none"} else target


def _count_from_prior(
    prior: tuple[MemberLedgerEntry, ...], when: date, rules: LifecycleRules
) -> Countability | None:
    by_row: dict[SourceReference, list[MemberLedgerEntry]] = defaultdict(list)
    for entry in prior:
        by_row[entry.record.source_reference].append(entry)
    decisions = {
        _count_from_row(_values(tuple(row)), when, rules) for row in by_row.values()
    }
    return next(iter(decisions)) if len(decisions) == 1 else None


def _count_from_row(
    values: dict[str, set[object]], when: date, rules: LifecycleRules
) -> Countability | None:
    member_type = _single(values["member_type"])
    is_company = _single(values["is_company"])
    is_member = _single(values["is_member"])
    if member_type is None or is_company is None or is_member is None:
        return None
    observation = LifecycleObservation(
        member_type=member_type,
        is_company=is_company == "True",
        is_member=is_member == "True",
        category=_single(values["category"]),
    )
    return _known_count(evaluate_countability(observation, when, rules).countability)
