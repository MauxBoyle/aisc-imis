"""Find and report likely duplicate company records in iMIS exports."""

from __future__ import annotations

import csv
import re
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import TypedDict
from xml.sax.saxutils import escape

from rapidfuzz.fuzz import ratio
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

REQUIRED_COLUMNS = {
    "Is Company",
    "Member Type",
    "iMIS Id",
    "Company",
    "Full Address",
}
REPORT_COLUMNS = [
    "left_id",
    "left_company",
    "left_address",
    "left_member_type",
    "left_status",
    "right_id",
    "right_company",
    "right_address",
    "right_member_type",
    "right_status",
    "zip_code",
    "address_score",
    "company_score",
]
ZIP_PATTERN = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
WHITESPACE_PATTERN = re.compile(r"\s+")
PUNCTUATION_PATTERN = re.compile(r"[^\w\s]")
ADDRESS_SUFFIXES = {
    "ave": "avenue",
    "blvd": "boulevard",
    "ct": "court",
    "dr": "drive",
    "hwy": "highway",
    "ln": "lane",
    "pkwy": "parkway",
    "rd": "road",
    "st": "street",
}


class Candidate(TypedDict):
    """A pair of company records that met duplicate-match thresholds."""

    left_id: str
    left_company: str
    left_address: str
    left_member_type: str
    left_status: str
    right_id: str
    right_company: str
    right_address: str
    right_member_type: str
    right_status: str
    zip_code: str
    address_score: float
    company_score: float


class CompanyRecord(TypedDict):
    """The source values needed to compare a company record."""

    record_id: str
    company: str
    address: str
    member_type: str
    status: str
    zip_code: str
    normalized_company: str
    normalized_address: str


def normalize_text(value: str) -> str:
    """Case-fold text, remove punctuation, standardize address suffixes, and trim it."""
    normalized = PUNCTUATION_PATTERN.sub(" ", value.casefold())
    normalized = WHITESPACE_PATTERN.sub(" ", normalized).strip()
    return " ".join(ADDRESS_SUFFIXES.get(word, word) for word in normalized.split())


def find_duplicate_candidates(
    input_path: Path,
    *,
    mode: str = "all",
    address_threshold: float = 90,
    name_threshold: float = 85,
) -> list[Candidate]:
    """Return deterministic pairs of likely duplicate company records from a CSV file.

    Matching is intentionally limited to records in the same five-digit ZIP code.
    In ``act`` mode, at least one record in each pair must have member type ACT.
    """
    if mode not in {"all", "act"}:
        raise ValueError("mode must be either 'all' or 'act'.")

    records_by_zip = _read_company_records(input_path)
    candidates: list[Candidate] = []
    for zip_code in sorted(records_by_zip):
        records = sorted(records_by_zip[zip_code], key=_record_sort_key)
        for left, right in combinations(records, 2):
            if mode == "act" and not _has_act_member_type(left, right):
                continue
            address_score = ratio(left["normalized_address"], right["normalized_address"])
            company_score = ratio(left["normalized_company"], right["normalized_company"])
            if address_score >= address_threshold and company_score >= name_threshold:
                candidates.append(
                    _candidate(left, right, address_score, company_score)
                )

    return sorted(candidates, key=lambda candidate: (candidate["left_id"], candidate["right_id"]))


def write_duplicate_reports(
    candidates: list[Candidate],
    output_dir: Path,
    *,
    mode: str,
    address_threshold: float,
    name_threshold: float,
    timestamp: str | None = None,
) -> tuple[Path, Path]:
    """Write CSV and PDF reports for duplicate candidates and return their paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    run_timestamp = timestamp or datetime.now().strftime("%Y%m%dT%H%M%S")
    stem = f"imis_duplicate_candidates_{mode}_{run_timestamp}"
    csv_path = output_dir / f"{stem}.csv"
    pdf_path = output_dir / f"{stem}.pdf"

    with csv_path.open("w", encoding="utf-8", newline="") as report_file:
        writer = csv.DictWriter(report_file, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(candidates)

    _write_pdf(pdf_path, candidates, mode, address_threshold, name_threshold)
    return csv_path, pdf_path


def _read_company_records(input_path: Path) -> dict[str, list[CompanyRecord]]:
    with input_path.open(encoding="utf-8-sig", newline="") as export_file:
        reader = csv.DictReader(export_file)
        headers = set(reader.fieldnames or [])
        missing_columns = sorted(REQUIRED_COLUMNS - headers)
        if missing_columns:
            raise ValueError(
                "Missing required CSV columns: " + ", ".join(missing_columns)
            )
        rows = list(reader)

    records_by_zip: dict[str, list[CompanyRecord]] = {}
    for row in rows:
        if (row["Is Company"] or "").strip().casefold() != "true":
            continue
        if "test" in (row["Company"] or "").casefold():
            continue
        address = (row["Full Address"] or "").strip()
        zip_code = _extract_zip(address)
        if not zip_code:
            continue
        record = CompanyRecord(
            record_id=(row["iMIS Id"] or "").strip(),
            company=(row["Company"] or "").strip(),
            address=address,
            member_type=(row["Member Type"] or "").strip(),
            status=(row.get("Status") or "").strip(),
            zip_code=zip_code,
            normalized_company=normalize_text(row["Company"] or ""),
            normalized_address=normalize_text(address),
        )
        records_by_zip.setdefault(zip_code, []).append(record)
    return records_by_zip


def _extract_zip(address: str) -> str | None:
    match = ZIP_PATTERN.search(address)
    return match.group(1) if match else None


def _record_sort_key(record: CompanyRecord) -> tuple[str, str, str]:
    return (record["record_id"], record["company"], record["address"])


def _has_act_member_type(left: CompanyRecord, right: CompanyRecord) -> bool:
    return left["member_type"].casefold() == "act" or right["member_type"].casefold() == "act"


def _candidate(
    left: CompanyRecord, right: CompanyRecord, address_score: float, company_score: float
) -> Candidate:
    return Candidate(
        left_id=left["record_id"],
        left_company=left["company"],
        left_address=left["address"],
        left_member_type=left["member_type"],
        left_status=left["status"],
        right_id=right["record_id"],
        right_company=right["company"],
        right_address=right["address"],
        right_member_type=right["member_type"],
        right_status=right["status"],
        zip_code=left["zip_code"],
        address_score=round(address_score, 2),
        company_score=round(company_score, 2),
    )


def _write_pdf(
    pdf_path: Path,
    candidates: list[Candidate],
    mode: str,
    address_threshold: float,
    name_threshold: float,
) -> None:
    styles = getSampleStyleSheet()
    story = [
        Paragraph("iMIS duplicate company candidates", styles["Title"]),
        Paragraph(
            f"Mode: {mode}; address threshold: {address_threshold}; "
            f"name threshold: {name_threshold}; matches: {len(candidates)}",
            styles["Normal"],
        ),
        Spacer(1, 12),
    ]
    for index, candidate in enumerate(candidates, start=1):
        story.extend(
            [
                Paragraph(
                    f"{index}. {_escaped(candidate['left_company'])} "
                    f"(ID {_escaped(candidate['left_id'])}) and "
                    f"{_escaped(candidate['right_company'])} "
                    f"(ID {_escaped(candidate['right_id'])})",
                    styles["Heading3"],
                ),
                Paragraph(
                    _address_line(
                        candidate["left_address"],
                        candidate["left_member_type"],
                        candidate["left_status"],
                    )
                    + "<br/>"
                    + _address_line(
                        candidate["right_address"],
                        candidate["right_member_type"],
                        candidate["right_status"],
                    ),
                    styles["Normal"],
                ),
                Paragraph(
                    f"ZIP: {_escaped(candidate['zip_code'])}; address score: "
                    f"{candidate['address_score']}; company score: "
                    f"{candidate['company_score']}",
                    styles["Normal"],
                ),
                Spacer(1, 10),
            ]
        )
    document = SimpleDocTemplate(str(pdf_path), pagesize=letter)
    document.build(story)


def _escaped(value: str) -> str:
    """Escape a CSV value before using it in ReportLab's paragraph markup."""
    return escape(value)


def _address_line(address: str, member_type: str, status: str) -> str:
    """Format one PDF address line with its member type and status codes."""
    return (
        f"{_escaped(address)} - Member Type: {_escaped(member_type)}; "
        f"Status: {_escaped(status)}"
    )
