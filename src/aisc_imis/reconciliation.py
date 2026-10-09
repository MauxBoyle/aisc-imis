"""Reconcile Certified Domestic Fabricator records between Salesforce and iMIS.

The matching functions accept records rather than file paths.  That keeps the
business rules usable when Salesforce is later supplied by its API instead of
by a CSV export.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import TypedDict
from xml.sax.saxutils import escape

from rapidfuzz.fuzz import ratio
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from aisc_imis.duplicates import normalize_text

SALESFORCE_REQUIRED_COLUMNS = {
    "Name",
    "BillingStreet",
    "BillingCity",
    "BillingState",
    "BillingPostalCode",
    "BillingCountry",
    "IMISID__c",
}
SALESFORCE_ID_COLUMNS = ("Certification_ID__c", "Id")
SALESFORCE_MEMBERSHIP_COLUMNS = ("InIMIS__c", "Certified_Fabricator__c")
SALESFORCE_ACTIVE_FOR_DISCOUNT_COLUMN = "Is_active_in_IMIS_for_Member_Discount__c"
IMIS_REQUIRED_COLUMNS = {"iMIS Id", "Company", "Full Address", "Member Type", "Status"}
REPORT_COLUMNS = [
    "salesforce_id",
    "salesforce_company",
    "salesforce_address",
    "salesforce_active_for_member_discount",
    "salesforce_imis_id",
    "match_group",
    "candidate_count",
    "candidate_imis_id",
    "candidate_company",
    "candidate_address",
    "candidate_member_type",
    "candidate_status",
    "address_score",
    "name_score",
    "imis_id_matches",
    "membership_status_matches",
]


class SalesforceRecord(TypedDict):
    """Values from one Salesforce fabricator record needed by the matcher."""

    salesforce_id: str
    company: str
    address: str
    in_imis: bool | None
    active_for_member_discount: bool | None
    imis_id: str


class ImisRecord(TypedDict):
    """Values from one iMIS company record needed by the matcher."""

    imis_id: str
    company: str
    address: str
    member_type: str
    status: str


class ReconciliationRow(TypedDict):
    """One report row, representing a Salesforce record and a candidate."""

    salesforce_id: str
    salesforce_company: str
    salesforce_address: str
    salesforce_active_for_member_discount: bool | None
    salesforce_imis_id: str
    match_group: str
    candidate_count: int
    candidate_imis_id: str
    candidate_company: str
    candidate_address: str
    candidate_member_type: str
    candidate_status: str
    address_score: float | str
    name_score: float | str
    imis_id_matches: bool | None
    membership_status_matches: bool | None


def read_salesforce_records(input_path: Path) -> list[SalesforceRecord]:
    """Read a Salesforce CSV export, preserving identifier strings.

    Current Certified Domestic Fabricator exports use ``Certification_ID__c``
    and ``InIMIS__c``. ``Id`` and ``Certified_Fabricator__c`` remain accepted
    for API-style exports.
    """
    rows = _read_salesforce_csv(input_path)
    records: list[SalesforceRecord] = []
    for row in rows:
        address = _join_address(
            row["BillingStreet"],
            row["BillingCity"],
            row["BillingState"],
            row["BillingPostalCode"],
            row["BillingCountry"],
        )
        records.append(
            SalesforceRecord(
                salesforce_id=_clean(_first_field(row, SALESFORCE_ID_COLUMNS)),
                company=_clean(row["Name"]),
                address=address,
                in_imis=_parse_boolean(
                    _first_field(row, SALESFORCE_MEMBERSHIP_COLUMNS)
                ),
                active_for_member_discount=_parse_boolean(
                    row.get(SALESFORCE_ACTIVE_FOR_DISCOUNT_COLUMN)
                ),
                imis_id=_clean(row["IMISID__c"]),
            )
        )
    return records


def read_imis_records(input_path: Path) -> list[ImisRecord]:
    """Read the iMIS CSV fields required for reconciliation."""
    rows = _read_csv(input_path, IMIS_REQUIRED_COLUMNS, "iMIS")
    return [
        ImisRecord(
            imis_id=_clean(row["iMIS Id"]),
            company=_clean(row["Company"]),
            address=_clean(row["Full Address"]),
            member_type=_clean(row["Member Type"]),
            status=_clean(row["Status"]),
        )
        for row in rows
    ]


def reconcile_records(
    salesforce_records: Iterable[SalesforceRecord],
    imis_records: Iterable[ImisRecord],
    *,
    address_threshold: float = 90,
    name_threshold: float = 50,
) -> list[ReconciliationRow]:
    """Return deterministic report rows for all Salesforce records.

    An eligible Salesforce record is compared with every eligible iMIS record.
    ZIP codes are deliberately not considered by this reconciliation.
    """
    _validate_thresholds(address_threshold, name_threshold)
    imis = sorted(list(imis_records), key=_imis_sort_key)
    normalized_imis = [
        (
            record,
            normalize_text(record["company"]),
            normalize_reconciliation_address(record["address"]),
        )
        for record in imis
        if _eligible(record["company"], record["address"])
    ]
    results: list[ReconciliationRow] = []
    for salesforce in salesforce_records:
        candidates: list[tuple[ImisRecord, float, float]] = []
        if _eligible(salesforce["company"], salesforce["address"]):
            normalized_company = normalize_text(salesforce["company"])
            normalized_address = normalize_reconciliation_address(salesforce["address"])
            for candidate, candidate_company, candidate_address in normalized_imis:
                address_score = ratio(normalized_address, candidate_address)
                name_score = ratio(normalized_company, candidate_company)
                if address_score >= address_threshold and name_score >= name_threshold:
                    candidates.append((candidate, round(address_score, 2), round(name_score, 2)))

        group = {0: "none", 1: "one"}.get(len(candidates), "many")
        if not candidates:
            results.append(_report_row(salesforce, None, "", "", group, 0))
            continue
        for candidate, address_score, name_score in candidates:
            results.append(
                _report_row(
                    salesforce,
                    candidate,
                    address_score,
                    name_score,
                    group,
                    len(candidates),
                )
            )
    return results


def write_reconciliation_reports(
    results: list[ReconciliationRow],
    output_dir: Path,
    *,
    address_threshold: float = 90,
    name_threshold: float = 50,
    timestamp: str | None = None,
) -> tuple[Path, Path]:
    """Write timestamped CSV and PDF investigation reports and return their paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    run_timestamp = timestamp or datetime.now().strftime("%Y%m%dT%H%M%S")
    stem = f"certified_fabricator_reconciliation_{run_timestamp}"
    csv_path = output_dir / f"{stem}.csv"
    pdf_path = output_dir / f"{stem}.pdf"
    with csv_path.open("w", encoding="utf-8", newline="") as report_file:
        writer = csv.DictWriter(report_file, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(results)
    _write_pdf(pdf_path, results, address_threshold, name_threshold)
    return csv_path, pdf_path


def _read_csv(path: Path, required: set[str], source: str) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as export_file:
        reader = csv.DictReader(export_file)
        headers = set(reader.fieldnames or [])
        missing = sorted(required - headers)
        if missing:
            raise ValueError(f"Missing required {source} CSV columns: " + ", ".join(missing))
        return list(reader)


def _read_salesforce_csv(path: Path) -> list[dict[str, str]]:
    """Read a supported Salesforce export and validate its alternate fields."""
    with path.open(encoding="utf-8-sig", newline="") as export_file:
        reader = csv.DictReader(export_file)
        headers = set(reader.fieldnames or [])
        missing = sorted(SALESFORCE_REQUIRED_COLUMNS - headers)
        if not headers.intersection(SALESFORCE_ID_COLUMNS):
            missing.append("Certification_ID__c or Id")
        if not headers.intersection(SALESFORCE_MEMBERSHIP_COLUMNS):
            missing.append("InIMIS__c or Certified_Fabricator__c")
        if missing:
            raise ValueError("Missing required Salesforce CSV columns: " + ", ".join(missing))
        return list(reader)


def _first_field(row: Mapping[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        if name in row:
            return row[name]
    raise KeyError(f"Expected one of: {', '.join(names)}")


def _join_address(*parts: str | None) -> str:
    return ", ".join(_clean(part) for part in parts if _clean(part))


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _parse_boolean(value: str | None) -> bool | None:
    normalized = _clean(value).casefold()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def normalize_reconciliation_address(value: str) -> str:
    """Normalize an address and remove non-comparable US country labels."""
    words = normalize_text(value).split()
    normalized_words: list[str] = []
    index = 0
    while index < len(words):
        if words[index] in {"us", "usa"}:
            index += 1
        elif words[index : index + 2] == ["united", "states"]:
            index += 2
        else:
            normalized_words.append(words[index])
            index += 1
    return " ".join(normalized_words)


def _eligible(company: str, address: str) -> bool:
    return bool(_clean(company) and _clean(address))


def _validate_thresholds(address_threshold: float, name_threshold: float) -> None:
    if not 0 <= address_threshold <= 100 or not 0 <= name_threshold <= 100:
        raise ValueError("Matching thresholds must be between 0 and 100.")


def _imis_sort_key(record: ImisRecord) -> tuple[str, str, str]:
    return (record["imis_id"], record["company"], record["address"])


def _report_row(
    salesforce: SalesforceRecord,
    candidate: ImisRecord | None,
    address_score: float | str,
    name_score: float | str,
    group: str,
    candidate_count: int,
) -> ReconciliationRow:
    assessed = group == "one" and candidate is not None
    is_active = bool(
        candidate
        and candidate["member_type"].casefold() == "act"
        and candidate["status"].casefold() == "a"
    )
    in_imis = salesforce["in_imis"]
    return ReconciliationRow(
        salesforce_id=salesforce["salesforce_id"],
        salesforce_company=salesforce["company"],
        salesforce_address=salesforce["address"],
        salesforce_active_for_member_discount=salesforce["active_for_member_discount"],
        salesforce_imis_id=salesforce["imis_id"],
        match_group=group,
        candidate_count=candidate_count,
        candidate_imis_id=candidate["imis_id"] if candidate else "",
        candidate_company=candidate["company"] if candidate else "",
        candidate_address=candidate["address"] if candidate else "",
        candidate_member_type=candidate["member_type"] if candidate else "",
        candidate_status=candidate["status"] if candidate else "",
        address_score=address_score,
        name_score=name_score,
        imis_id_matches=(salesforce["imis_id"] == candidate["imis_id"]) if assessed else None,
        membership_status_matches=(in_imis == is_active)
        if assessed and in_imis is not None
        else None,
    )


def _write_pdf(
    pdf_path: Path,
    results: list[ReconciliationRow],
    address_threshold: float,
    name_threshold: float,
) -> None:
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Certified Domestic Fabricator reconciliation", styles["Title"]),
        Paragraph(
            f"Address threshold: {address_threshold}; name threshold: {name_threshold}. "
            "ZIP codes are not used for matching.",
            styles["Normal"],
        ),
        Spacer(1, 12),
    ]
    headings = (("none", "No matches"), ("one", "Exactly one match"), ("many", "Multiple matches"))
    for group, heading in headings:
        grouped = [row for row in results if row["match_group"] == group]
        story.append(Paragraph(f"{heading} ({len(grouped)} rows)", styles["Heading2"]))
        if not grouped:
            story.append(Paragraph("None", styles["Normal"]))
        for row in grouped:
            story.append(Paragraph(_pdf_row(row), styles["Normal"]))
            story.append(Spacer(1, 6))
    SimpleDocTemplate(str(pdf_path), pagesize=letter).build(story)


def _pdf_row(row: Mapping[str, object]) -> str:
    def field(name: str) -> str:
        value = row[name]
        return escape("" if value is None else str(value))

    return (
        f"Salesforce: {field('salesforce_company')} (ID {field('salesforce_id')})<br/>"
        f"Address: {field('salesforce_address')}; active for member discount: "
        f"{field('salesforce_active_for_member_discount')}; "
        f"Salesforce iMIS ID: {field('salesforce_imis_id')}<br/>"
        f"Candidate: {field('candidate_company')} (iMIS ID {field('candidate_imis_id')}); "
        f"address: {field('candidate_address')}; type/status: "
        f"{field('candidate_member_type')}/{field('candidate_status')}<br/>"
        f"Candidates: {field('candidate_count')}; address/name scores: "
        f"{field('address_score')}/{field('name_score')}; iMIS ID matches: "
        f"{field('imis_id_matches')}; membership status matches: "
        f"{field('membership_status_matches')}"
    )
