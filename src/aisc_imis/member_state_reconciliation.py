"""Compare membership observations with independently known member history."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from aisc_imis.current_member_records import CurrentMemberObservation
from aisc_imis.evidence_ledger import ObservedFact, SnapshotStateObservation
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
from aisc_imis.member_state_history import FIELDS, MemberStateHistory, day, unique
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
    observation: MembershipObservation
    comparison_date: date | None
    outcome: str
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
    """Compare each row with evidence available before its comparison date."""
    dated = tuple(
        (item, item.observation_date) for item in historical_observations
    ) + tuple((item, current_export_date) for item in current_observations)
    records = [entry.record for entry in evidence.entries]
    for item, when in dated:
        if not item.subject_key.strip():
            raise ValueError("Observation subject_key must be nonblank.")
        records.extend(_as_snapshot_records(item, when))
    ledger = build_member_evidence_ledger(records)
    entries = unique(ledger.entries)
    by_subject: dict[str, list[MemberLedgerEntry]] = defaultdict(list)
    targets: dict[tuple[str, SourceReference, date | None], list[MemberLedgerEntry]] = (
        defaultdict(list)
    )
    same_day: dict[tuple[str, date, str], set[object]] = defaultdict(set)
    same_day_entries: dict[tuple[str, date, str], list[MemberLedgerEntry]] = (
        defaultdict(list)
    )
    for entry in entries:
        record = entry.record
        by_subject[record.subject_key].append(entry)
        if isinstance(record, (SnapshotStateObservation, ObservedFact)):
            targets[
                record.subject_key, record.source_reference, day(record.observed_date)
            ].append(entry)
        if isinstance(record, SnapshotStateObservation):
            field, separator, value = record.state_name.partition("=")
            when = day(record.observed_date)
            if separator and field in FIELDS and when is not None:
                key = (record.subject_key, when, field)
                same_day[key].add(value)
                same_day_entries[key].append(entry)
    histories = {
        subject: MemberStateHistory(tuple(group), rules)
        for subject, group in by_subject.items()
    }
    findings: list[ReconciliationFinding] = []
    for key, values in sorted(same_day.items()):
        if len(values) > 1:
            subject, when, field = key
            findings.append(
                build_finding(
                    "snapshot_state_conflict",
                    subject,
                    f"{when.isoformat()}:{field}",
                    supporting_evidence=same_day_entries[key],
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
        target = tuple(targets[item.subject_key, item.source_reference, when])
        if when is None:
            findings.append(
                build_finding(
                    "missing_lifecycle_date",
                    item.subject_key,
                    f"undated:{item.source_reference.source_name}:{item.source_reference.row_reference}",
                    supporting_evidence=target,
                )
            )
            comparisons.append(
                MembershipComparison(
                    item, None, "unassessable", None, None, None, None, ()
                )
            )
            continue
        state = histories[item.subject_key].state_before(when)
        scope = f"{when.isoformat()}:{item.source_reference.source_name}:{item.source_reference.row_reference}"
        observed_decision = evaluate_countability(
            LifecycleObservation(
                item.member_type,
                item.is_company,
                item.is_member,
                item.category,
                status=item.status,
            ),
            when,
            rules,
        )
        observed_count = _known(observed_decision.countability)
        expected_count = _known(state.countability.value)
        has_history = any(
            point.known <= when
            and (
                point.applies < when
                or (point.applies == when and point.event_target is not None)
            )
            for point in histories[item.subject_key].points
        )
        differences = False
        incomplete = False
        support: list[MemberLedgerEntry] = []
        for field in ("member_type", "status"):
            observed = getattr(item, field)
            if observed is None:
                incomplete = True
                findings.append(
                    build_finding(
                        "missing_observed_state_field",
                        item.subject_key,
                        f"{scope}:{field}",
                        supporting_evidence=target,
                    )
                )
                continue
            expected = state.field(field)
            support.extend(expected.evidence)
            if expected.value is None:
                incomplete = True
                if expected.evidence or has_history:
                    findings.append(
                        build_finding(
                            expected.reason or "unassessable_state_field",
                            item.subject_key,
                            f"{scope}:{field}",
                            supporting_evidence=expected.evidence or target,
                            contradicting_evidence=target if expected.evidence else (),
                        )
                    )
            elif expected.value != observed:
                differences = True
                findings.append(
                    build_finding(
                        "possible_missing_transition",
                        item.subject_key,
                        f"{scope}:{field}",
                        supporting_evidence=expected.evidence,
                        contradicting_evidence=target,
                    )
                )
        support.extend(state.countability.evidence)
        if expected_count is None:
            incomplete = True
            if state.countability.evidence or has_history:
                findings.append(
                    build_finding(
                        state.countability.reason
                        or "unassessable_countability_snapshot",
                        item.subject_key,
                        f"{scope}:countability:expected",
                        supporting_evidence=state.countability.evidence or target,
                        contradicting_evidence=(
                            target if state.countability.evidence else ()
                        ),
                    )
                )
        if observed_count is None:
            incomplete = True
            findings.append(
                build_finding(
                    observed_decision.findings[0].code
                    if observed_decision.findings
                    else "unassessable_countability_snapshot",
                    item.subject_key,
                    f"{scope}:countability:observed",
                    supporting_evidence=target,
                )
            )
        if (
            expected_count is not None
            and observed_count is not None
            and expected_count != observed_count
        ):
            differences = True
            findings.append(
                build_finding(
                    "countability_difference",
                    item.subject_key,
                    f"{scope}:countability",
                    supporting_evidence=state.countability.evidence,
                    contradicting_evidence=target,
                )
            )
                )
        if not has_history:
            incomplete = True
            findings.append(
                build_finding(
                    "unknown_starting_state",
                    item.subject_key,
                    scope,
                    supporting_evidence=target,
                )
            )
        if incomplete:
            outcome = "unassessable"
        elif differences:
            outcome = "discrepancy"
        else:
            outcome = "match"
        comparisons.append(
            MembershipComparison(
                item,
                when,
                outcome,
                _text(state.field("member_type").value),
                _text(state.field("status").value),
                expected_count,
                observed_count,
                tuple(entry.record_id for entry in unique(support)),
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
        for field in FIELDS
        if (value := getattr(item, field)) is not None
    )
    return (anchor, *fields)


def _known(value: object) -> Countability | None:
    return (
        value
        if isinstance(value, Countability) and value != Countability.UNKNOWN
        else None
    )


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None
