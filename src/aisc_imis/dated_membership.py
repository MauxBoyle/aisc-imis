"""Select a supported first join without confusing evidence time with event time."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime

from aisc_imis.evidence_ledger import (
    CandidateLifecycleEvent,
    ObservedFact,
    SnapshotStateObservation,
)
from aisc_imis.lifecycle_rules import (
    Countability,
    LifecycleObservation,
    LifecycleRules,
    evaluate_countability,
)
from aisc_imis.member_ledger import MemberLedgerEntry


def day(value: date | datetime | None) -> date | None:
    return value.date() if isinstance(value, datetime) else value


def rule_date(when: date, rules: LifecycleRules) -> date:
    """Use the earliest reviewed taxonomy for source events before its start."""
    return max(when, min(rule.effective_reporting_date for rule in rules.rules))


def known_by(entry: MemberLedgerEntry, cutoff: date) -> bool:
    record = entry.record
    # The observation date is the availability date for a snapshot, even when
    # its Last Updated value predates the export.
    available = (day(record.recorded_date) or day(record.observed_date)) if isinstance(record, CandidateLifecycleEvent) else (day(record.observed_date) or day(record.recorded_date))
    return available is not None and available <= cutoff


@dataclass(frozen=True)
class JoinSelection:
    effective_date: date | None
    evidence: tuple[MemberLedgerEntry, ...]
    findings: tuple[str, ...] = ()


def select_first_join(
    entries: Iterable[MemberLedgerEntry], rules: LifecycleRules, cutoff: date
) -> JoinSelection:
    """Require a countable company snapshot and one unambiguous Join Date."""
    visible = tuple(entry for entry in entries if known_by(entry, cutoff))
    groups: dict[tuple[object, ...], list[MemberLedgerEntry]] = defaultdict(list)
    for entry in visible:
        record = entry.record
        if isinstance(record, SnapshotStateObservation):
            groups[(record.source_reference, record.observed_date, record.recorded_date)].append(entry)
    supporters: list[MemberLedgerEntry] = []
    for group in groups.values():
        values: dict[str, object] = {}
        for entry in group:
            field, _, raw = entry.record.state_name.partition("=")
            values[field] = raw.lower() == "true" if field in {"is_company", "is_member"} else raw
        if values.get("is_company") is not True:
            continue
        observation = LifecycleObservation(
            member_type=values.get("member_type"),
            is_company=values.get("is_company"),
            is_member=values.get("is_member"),
            status=values.get("status"),
            category=values.get("category"),
        )
        if evaluate_countability(observation, rule_date(day(group[0].record.observed_date) or cutoff, rules), rules).countability is Countability.COUNTABLE:
            supporters.extend(group)
    if not supporters:
        return JoinSelection(None, ())
    dates: dict[date, list[MemberLedgerEntry]] = defaultdict(list)
    invalid = []
    for entry in visible:
        record = entry.record
        if not isinstance(record, ObservedFact) or record.fact_name != "join_date":
            continue
        try:
            dates[date.fromisoformat(record.fact_value)].append(entry)
        except ValueError:
            invalid.append(entry)
    if len(dates) > 1:
        return JoinSelection(None, tuple(item for group in dates.values() for item in group), ("conflicting_join_dates",))
    if not dates:
        return JoinSelection(None, tuple(invalid), ("invalid_join_date",) if invalid else ())
    when, sources = next(iter(dates.items()))
    return JoinSelection(when, (*sources, *supporters), ("invalid_join_date",) if invalid else ())
