"""Compare membership observations with evidence available independently of that date.

The caller has already confirmed subject keys. This module neither links people
nor treats an unexplained change as proof that any source row is wrong.
"""

from __future__ import annotations

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
    records = tuple(entry.record for entry in evidence.entries)
    for item, when in dated:
        if not item.subject_key.strip():
            raise ValueError("Observation subject_key must be nonblank.")
        records += _as_snapshot_records(item, when)
    ledger = build_member_evidence_ledger(records)
    # Identical records can arrive both in the confirmed ledger and as supplied
    # observations. Keep one copy for comparison and stable evidence citations.
    entries = tuple({entry.record_id: entry for entry in ledger.entries}.values())
    entries = tuple(sorted(entries, key=lambda entry: entry.record_id))
    targets: dict[
        tuple[str, date],
        list[tuple[MembershipObservation, tuple[MemberLedgerEntry, ...]]],
    ] = defaultdict(list)
    for item, when in dated:
        if when is not None:
            target_entries = tuple(
                entry
                for entry in entries
                if isinstance(entry.record, (SnapshotStateObservation, ObservedFact))
                and entry.record.subject_key == item.subject_key
                and entry.record.source_reference == item.source_reference
                and _day(entry.record.observed_date) == when
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
                entry
                for entry in entries
                if (
                    isinstance(entry.record, (SnapshotStateObservation, ObservedFact))
                    and entry.record.subject_key == item.subject_key
                    and entry.record.source_reference == item.source_reference
                    and entry.record.observed_date is None
                )
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
        target_entries = dict(targets[item.subject_key, when])[item]
        earlier = tuple(
            entry
            for entry in entries
            if (
                entry.record.subject_key == item.subject_key
                and isinstance(entry.record, SnapshotStateObservation)
                and (_snapshot_day(entry) or date.max) < when
            )
        )
        latest_day = max((_snapshot_day(entry) for entry in earlier), default=None)
        prior = tuple(entry for entry in earlier if _snapshot_day(entry) == latest_day)
        intervening_events = tuple(
            entry
            for entry in entries
            if (
                entry.record.subject_key == item.subject_key
                and isinstance(entry.record, CandidateLifecycleEvent)
                and _day(entry.record.effective_date) is not None
                and _day(entry.record.effective_date) <= when
                and (
                    _day(entry.record.recorded_date)
                    or _day(entry.record.observed_date)
                    or date.max
                )
                <= when
                and (
                    latest_day is None or _day(entry.record.effective_date) > latest_day
                )
                and _event_target(entry, when, rules) is not None
            )
        )
        unresolved = tuple(
            entry
            for entry in intervening_events
            if entry.record.interpretation_status in {"ambiguous", "unresolved"}
        )
        events = tuple(entry for entry in intervening_events if entry not in unresolved)
        event_day = max(
            (_day(entry.record.effective_date) for entry in events), default=None
        )
        latest_events = tuple(
            entry for entry in events if _day(entry.record.effective_date) == event_day
        )
        prior_values = _values(prior)
        expected_type = _single(prior_values["member_type"])
        expected_status = _single(prior_values["status"])
        type_support = prior
        count_support = prior
        # Only an event with an explicit Member Type can update that field.
        # Later events without one leave the last supported type in place.
        typed_events = tuple(entry for entry in events if entry.record.member_type)
        if typed_events:
            type_day = max(_day(entry.record.effective_date) for entry in typed_events)
            type_support = tuple(
                entry
                for entry in typed_events
                if _day(entry.record.effective_date) == type_day
            )
            expected_type = _single(
                {entry.record.member_type for entry in type_support}
            )
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
            elif prior and latest_day is not None:
                expected_count = _count_from_prior(prior, when, rules)

        scope = f"{when.isoformat()}:{item.source_reference.source_name}:{item.source_reference.row_reference}"
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
            ("status", expected_status, item.status, prior),
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
                            for entry in (*type_support, *prior, *count_support)
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
