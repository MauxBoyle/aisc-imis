"""Convert normalized iMIS adapter observations into immutable ledger evidence.

This module is intentionally a Python API, not a command-line program.  It
does not join subjects, sort rows, export files, or reconstruct a lifecycle.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from aisc_imis.activity_history_records import ActivityHistoryObservation
from aisc_imis.current_member_records import CurrentMemberObservation
from aisc_imis.evidence_ledger import (
    CandidateLifecycleEvent,
    DateValue,
    InterpretationStatus,
    LedgerRecord,
    ObservedFact,
    SnapshotStateObservation,
)
from aisc_imis.historical_snapshot_records import HistoricalSnapshotObservation
from aisc_imis.membership_change_records import MembershipChangeObservation
from aisc_imis.normalization_contracts import SourceReference


@dataclass(frozen=True)
class ConversionFinding:
    """A conversion meaning that needs review, tied to its source row."""

    code: str
    message: str
    reference: SourceReference


@dataclass(frozen=True)
class EvidenceConversionResult:
    """Ordered converted records and findings from one adapter input type."""

    records: tuple[LedgerRecord, ...]
    findings: tuple[ConversionFinding, ...]


def convert_current_member_observations(
    observations: Iterable[CurrentMemberObservation],
) -> EvidenceConversionResult:
    """Turn present-state rows into state observations using normalized iMIS IDs."""
    records: list[LedgerRecord] = []
    for observation in observations:
        records.extend(
            _snapshot_states(
                subject_key=observation.imis_id,
                reference=observation.record.reference,
                recorded_date=observation.last_updated,
                observed_date=None,
                member_type=observation.member_type,
                status=observation.status,
                is_member=observation.is_member,
                is_company=observation.is_company,
            )
        )
    return EvidenceConversionResult(tuple(records), ())


def convert_historical_snapshot_observations(
    observations: Iterable[HistoricalSnapshotObservation],
) -> EvidenceConversionResult:
    """Turn historical rows into state observations with configured coverage dates."""
    records: list[LedgerRecord] = []
    for observation in observations:
        records.extend(
            _snapshot_states(
                subject_key=observation.imis_id,
                reference=observation.record.reference,
                recorded_date=observation.last_updated,
                observed_date=observation.observation_date,
                member_type=observation.member_type,
                status=observation.status,
                is_member=observation.is_member,
                is_company=observation.is_company,
            )
        )
    return EvidenceConversionResult(tuple(records), ())


def convert_membership_change_observations(
    observations: Iterable[MembershipChangeObservation],
) -> EvidenceConversionResult:
    """Convert reviewed change types; retain every other change type as a fact."""
    records: list[LedgerRecord] = []
    findings: list[ConversionFinding] = []
    for observation in observations:
        classification = observation.change_classification
        if _has_lifecycle_name(classification):
            records.append(
                CandidateLifecycleEvent(
                    subject_key=observation.change_id,
                    event_name=classification.draft_lifecycle_name,
                    source_references=(observation.record.reference,),
                    interpretation_reason=(
                        "Reviewed Membership changes / Change Type taxonomy maps "
                        f"{observation.change_type!r} to "
                        f"{classification.draft_lifecycle_name!r}."
                    ),
                    # The reviewed default for a membership-change event is
                    # when it was created.  ``ChangeEffective`` remains in
                    # the immutable source row for later backdating review;
                    # it is not silently used as the event date.
                    effective_date=observation.change_created,
                    recorded_date=observation.change_created,
                )
            )
            continue
        records.append(_unresolved_change_fact(observation))
        findings.append(
            _unresolved_finding(
                "unresolved_change_type_conversion",
                "Membership change type was retained as unresolved evidence, not a lifecycle event.",
                observation.record.reference,
            )
        )
    return EvidenceConversionResult(tuple(records), tuple(findings))


def convert_activity_history_observations(
    observations: Iterable[ActivityHistoryObservation],
) -> EvidenceConversionResult:
    """Convert lifecycle mappings and preserve DUES as non-transition evidence."""
    records: list[LedgerRecord] = []
    findings: list[ConversionFinding] = []
    for observation in observations:
        classification = observation.activity_classification
        if observation.activity_type == "DUES" and _is_payment_activity(classification):
            records.append(
                ObservedFact(
                    subject_key=observation.imis_id,
                    fact_name="payment_activity",
                    fact_value=observation.activity_type,
                    source_reference=observation.record.reference,
                    effective_date=observation.effective_date,
                    recorded_date=observation.transaction_date,
                )
            )
        elif _has_lifecycle_name(classification):
            records.append(
                CandidateLifecycleEvent(
                    subject_key=observation.imis_id,
                    event_name=classification.draft_lifecycle_name,
                    source_references=(observation.record.reference,),
                    interpretation_reason=(
                        "Reviewed Activity history / Activity Type taxonomy maps "
                        f"{observation.activity_type!r} to "
                        f"{classification.draft_lifecycle_name!r}."
                    ),
                    effective_date=observation.effective_date,
                    recorded_date=observation.transaction_date,
                )
            )
        else:
            records.append(
                ObservedFact(
                    subject_key=observation.imis_id,
                    fact_name="activity_type",
                    fact_value=observation.activity_type,
                    source_reference=observation.record.reference,
                    effective_date=observation.effective_date,
                    recorded_date=observation.transaction_date,
                    interpretation_status=InterpretationStatus.UNRESOLVED,
                )
            )
            findings.append(
                _unresolved_finding(
                    "unresolved_activity_type_conversion",
                    "Activity type was retained as unresolved evidence, not a lifecycle event.",
                    observation.record.reference,
                )
            )
    return EvidenceConversionResult(tuple(records), tuple(findings))


def _snapshot_states(
    *,
    subject_key: str,
    reference: SourceReference,
    recorded_date: DateValue | None,
    observed_date: DateValue | None,
    member_type: str | None,
    status: str | None,
    is_member: bool | None,
    is_company: bool | None,
) -> tuple[SnapshotStateObservation, ...]:
    values = (
        ("member_type", member_type),
        ("status", status),
        ("is_member", is_member),
        ("is_company", is_company),
    )
    return tuple(
        SnapshotStateObservation(
            subject_key=subject_key,
            state_name=f"{field}={value}",
            source_reference=reference,
            recorded_date=recorded_date,
            observed_date=observed_date,
        )
        for field, value in values
        if value is not None
    )


def _unresolved_change_fact(observation: MembershipChangeObservation) -> ObservedFact:
    return ObservedFact(
        subject_key=observation.change_id,
        fact_name="change_type",
        fact_value=observation.change_type,
        source_reference=observation.record.reference,
        effective_date=observation.change_effective,
        recorded_date=observation.change_created,
        interpretation_status=InterpretationStatus.UNRESOLVED,
    )


def _has_lifecycle_name(classification: object) -> bool:
    name = getattr(classification, "draft_lifecycle_name", "")
    effect = getattr(classification, "countability_effect", "")
    return bool(name and name != "unknown" and effect != "unresolved")


def _is_payment_activity(classification: object) -> bool:
    return getattr(classification, "evidence_class", "") == "payment activity"


def _unresolved_finding(
    code: str, message: str, reference: SourceReference
) -> ConversionFinding:
    return ConversionFinding(code=code, message=message, reference=reference)
