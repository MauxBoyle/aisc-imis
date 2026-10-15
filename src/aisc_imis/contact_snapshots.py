"""Combine overlapping CSContactBasic snapshot exports."""

from __future__ import annotations

import csv
import re
import sqlite3
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

KEY_COLUMNS = ("iMIS Id", "Last Updated")
PROCESS_COLUMNS = {"isMax", "maxUpdate", "Table Names"}
EXCLUDED_SOURCE_FILES = {"Full_CSContactBasic_MB_1.csv"}
PREFERRED_COMPANY_NAMES = {
    "Barry Isett and Associates": "Barry Isett & Associates, Inc.",
}
BRANCH_MEMBER_TYPES = {
    "ACT": "ACTB",
    "AFF": "AFFB",
    "ASSOC": "ASSCB",
    "FACT": "FACTB",
    "FASSC": "FASCB",
    "FPROF": "FPROB",
    "PROF": "PROFB",
}
MEMBER_TYPES_WITH_IS_MEMBER_TRUE = {"PROFB", "PROFD"}
COMPANY_MEMBER_TYPE_BY_MEMBER_TYPE = {
    "ACTD": "ACT",
    "AFFD": "AFF",
    "FASCD": "FASSC",
    "NM": "NMC",
    "PACTD": "PACT",
    "PROFD": "PROF",
    "STU": "UNIV",
}
EXCLUDED_CONFLICT_KEYS = {
    # User-approved removal of irreconcilable historical duplicate pairs.
    ("3244293", "6/5/2025 10:55:23 AM"),
    ("3411085", "1/13/2026 11:46:06 AM"),
    # User-approved removal of pre-2026 Member Status conflict pairs.
    ("1005030", "6/5/2025 10:14:06 AM"),
    ("1077865", "6/2/2025 9:25:52 AM"),
    ("1117147", "6/26/2025 2:09:36 PM"),
    ("3220255", "6/19/2025 10:19:43 AM"),
    ("3366120", "6/19/2025 10:00:44 AM"),
    # User-approved removal of all remaining unresolved conflict pairs.
    ("1036925", "7/18/2025 7:00:08 AM"),
    ("1038405", "7/18/2025 7:00:08 AM"),
    ("1049462", "7/18/2025 7:00:08 AM"),
    ("1051782", "3/12/2026 6:22:22 PM"),
    ("1071380", "2/6/2026 3:40:36 AM"),
    ("1080326", "7/18/2025 7:00:08 AM"),
    ("1082658", "2/5/2026 3:02:33 AM"),
    ("1092828", "7/18/2025 7:00:08 AM"),
    ("1096346", "7/18/2025 7:00:08 AM"),
    ("1096347", "7/18/2025 7:00:08 AM"),
    ("1096348", "7/18/2025 7:00:08 AM"),
    ("1096349", "7/18/2025 7:00:08 AM"),
    ("1096351", "7/18/2025 7:00:08 AM"),
    ("1097114", "7/18/2025 7:00:08 AM"),
    ("1111456", "2/5/2026 4:43:32 AM"),
    ("3006217", "2/5/2026 4:43:26 AM"),
    ("3006799", "2/5/2026 3:20:21 AM"),
    ("3007853", "2/5/2026 4:34:44 AM"),
    ("3015371", "7/18/2025 7:00:08 AM"),
    ("3040107", "2/27/2026 11:45:41 AM"),
    ("3058588", "2/2/2026 10:44:21 AM"),
    ("3073108", "7/18/2025 7:00:08 AM"),
    ("3073112", "7/18/2025 7:00:08 AM"),
    ("3073114", "7/18/2025 7:00:08 AM"),
    ("3073117", "7/18/2025 7:00:08 AM"),
    ("3073118", "7/18/2025 7:00:08 AM"),
    ("3073119", "7/18/2025 7:00:08 AM"),
    ("3073121", "7/18/2025 7:00:08 AM"),
    ("3189928", "7/18/2025 7:00:08 AM"),
    ("3189929", "7/18/2025 7:00:08 AM"),
    ("3401621", "7/18/2025 7:00:08 AM"),
}


@dataclass(frozen=True)
class MergeStats:
    """Counts that explain what a snapshot merge did."""

    input_files: int
    input_rows: int
    exact_unique_rows: int
    output_rows: int
    coalesced_rows: int


@dataclass(frozen=True)
class SplitStats:
    """Counts that explain how a combined snapshot file was divided."""

    input_rows: int
    member_ids: int
    current_rows: int
    history_rows: int


def find_snapshot_files(input_dir: Path) -> list[Path]:
    """Return CSV files whose names contain ``CSContactBasic``."""
    return sorted(
        (
            path
            for path in input_dir.iterdir()
            if path.is_file()
            and path.suffix.casefold() == ".csv"
            and "cscontactbasic" in path.name.casefold()
            and path.name not in EXCLUDED_SOURCE_FILES
        ),
        key=lambda path: path.name.casefold(),
    )


def combine_contact_snapshots(
    input_paths: Sequence[Path], output_path: Path
) -> MergeStats:
    """Combine snapshots, filling blanks only when populated values do not conflict.

    Rows are compared only within the same iMIS ID and Last Updated value. Exact
    duplicate rows are removed first. Remaining compatible rows are coalesced,
    while rows containing conflicting populated values remain separate. Known
    formatting-only variants are standardized before comparison.
    """
    if not input_paths:
        raise ValueError("No input snapshot files were provided.")

    columns = _collect_columns(input_paths)
    missing_keys = [column for column in KEY_COLUMNS if column not in columns]
    if missing_keys:
        raise ValueError("Missing required columns: " + ", ".join(missing_keys))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="contact_snapshot_merge_") as temp_dir:
        database_path = Path(temp_dir) / "rows.sqlite3"
        connection = sqlite3.connect(database_path)
        try:
            _create_staging_table(connection, columns)
            input_rows = _load_rows(connection, input_paths, columns)
            exact_unique_rows = _count_rows(connection)
            parent_member_types = _latest_parent_member_types(connection, columns)
            output_rows = _replace_with_merged_rows(
                connection, columns, output_path, parent_member_types
            )
        finally:
            connection.close()

    return MergeStats(
        input_files=len(input_paths),
        input_rows=input_rows,
        exact_unique_rows=exact_unique_rows,
        output_rows=output_rows,
        coalesced_rows=exact_unique_rows - output_rows,
    )


def split_contact_snapshots(
    input_path: Path, current_path: Path, history_path: Path
) -> SplitStats:
    """Split combined snapshots into the newest and older row for each iMIS ID.

    The input is read twice so complete CSV rows do not need to be held in
    memory. A member with two rows at the same newest timestamp is rejected
    because choosing one automatically could hide a source conflict.
    """
    paths = {input_path.resolve(), current_path.resolve(), history_path.resolve()}
    if len(paths) != 3:
        raise ValueError("Input, current, and history paths must be different.")

    latest_by_id: dict[str, tuple[str, str]] = {}
    latest_counts: dict[str, int] = {}
    input_rows = 0

    with input_path.open(encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        columns = reader.fieldnames or []
        missing = [column for column in KEY_COLUMNS if column not in columns]
        if missing:
            raise ValueError("Missing required columns: " + ", ".join(missing))

        for row_number, row in enumerate(reader, start=2):
            imis_id = (row["iMIS Id"] or "").strip()
            updated = (row["Last Updated"] or "").strip()
            if not imis_id:
                raise ValueError(f"Blank iMIS Id on CSV row {row_number}.")
            if not updated:
                raise ValueError(
                    f"Blank Last Updated value for iMIS Id {imis_id} "
                    f"on CSV row {row_number}."
                )
            try:
                sort_key = _date_sort_key(updated)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"Invalid Last Updated value {updated!r} for iMIS Id "
                    f"{imis_id} on CSV row {row_number}."
                ) from error

            input_rows += 1
            previous = latest_by_id.get(imis_id)
            if previous is None or sort_key > previous[0]:
                latest_by_id[imis_id] = (sort_key, updated)
                latest_counts[imis_id] = 1
            elif sort_key == previous[0]:
                latest_counts[imis_id] += 1

    tied_ids = sorted(imis_id for imis_id, count in latest_counts.items() if count > 1)
    if tied_ids:
        examples = ", ".join(tied_ids[:5])
        raise ValueError(
            f"{len(tied_ids)} iMIS Id values have multiple rows at their newest "
            f"timestamp. Resolve them before splitting. Examples: {examples}"
        )

    current_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=current_path.parent,
            prefix=f".{current_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as current_file,
        tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=history_path.parent,
            prefix=f".{history_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as history_file,
    ):
        current_temporary_path = Path(current_file.name)
        history_temporary_path = Path(history_file.name)
        current_writer = csv.DictWriter(current_file, fieldnames=columns)
        history_writer = csv.DictWriter(history_file, fieldnames=columns)
        current_writer.writeheader()
        history_writer.writeheader()
        current_rows = 0
        history_rows = 0

        with input_path.open(encoding="utf-8-sig", newline="") as input_file:
            for row in csv.DictReader(input_file):
                imis_id = (row["iMIS Id"] or "").strip()
                updated = (row["Last Updated"] or "").strip()
                if updated == latest_by_id[imis_id][1]:
                    current_writer.writerow(row)
                    current_rows += 1
                else:
                    history_writer.writerow(row)
                    history_rows += 1

    try:
        current_temporary_path.replace(current_path)
        history_temporary_path.replace(history_path)
    finally:
        current_temporary_path.unlink(missing_ok=True)
        history_temporary_path.unlink(missing_ok=True)

    return SplitStats(
        input_rows=input_rows,
        member_ids=len(latest_by_id),
        current_rows=current_rows,
        history_rows=history_rows,
    )


def _collect_columns(input_paths: Sequence[Path]) -> list[str]:
    columns: list[str] = []
    for path in input_paths:
        with path.open(encoding="utf-8-sig", newline="") as input_file:
            headers = next(csv.reader(input_file), [])
        if not headers:
            raise ValueError(f"Input CSV is empty: {path}")
        for header in headers:
            if header not in PROCESS_COLUMNS and header not in columns:
                columns.append(header)
    return columns


def _create_staging_table(
    connection: sqlite3.Connection, columns: Sequence[str]
) -> None:
    column_sql = ", ".join(f'"c{index}" TEXT NOT NULL' for index in range(len(columns)))
    unique_sql = ", ".join(f'"c{index}"' for index in range(len(columns)))
    connection.execute(
        f"CREATE TABLE rows ({column_sql}, completeness INTEGER NOT NULL, "
        f"UNIQUE ({unique_sql}))"
    )
    id_index = columns.index(KEY_COLUMNS[0])
    date_index = columns.index(KEY_COLUMNS[1])
    connection.execute(
        f'CREATE INDEX row_keys ON rows ("c{id_index}", "c{date_index}")'
    )


def _load_rows(
    connection: sqlite3.Connection,
    input_paths: Sequence[Path],
    columns: Sequence[str],
) -> int:
    placeholders = ", ".join("?" for _ in range(len(columns) + 1))
    insert_sql = f"INSERT OR IGNORE INTO rows VALUES ({placeholders})"
    input_rows = 0
    id_index = columns.index("iMIS Id")
    date_index = columns.index("Last Updated")

    for path in input_paths:
        with path.open(encoding="utf-8-sig", newline="") as input_file:
            reader = csv.DictReader(input_file)
            batch: list[tuple[str | int, ...]] = []
            for source_row in reader:
                values = tuple(
                    _clean_value(column, source_row.get(column) or "")
                    for column in columns
                )
                input_rows += 1
                key = (values[id_index], values[date_index])
                if key in EXCLUDED_CONFLICT_KEYS:
                    continue
                completeness = sum(bool(value) for value in values)
                batch.append((*values, completeness))
                if len(batch) == 10_000:
                    connection.executemany(insert_sql, batch)
                    batch.clear()
            if batch:
                connection.executemany(insert_sql, batch)
        connection.commit()

    return input_rows


def _count_rows(connection: sqlite3.Connection) -> int:
    result = connection.execute("SELECT COUNT(*) FROM rows").fetchone()
    assert result is not None
    return int(result[0])


def _replace_with_merged_rows(
    connection: sqlite3.Connection,
    columns: Sequence[str],
    output_path: Path,
    parent_member_types: dict[str, str],
) -> int:
    with tempfile.NamedTemporaryFile(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary_file:
        temporary_path = Path(temporary_file.name)
    try:
        output_rows = _write_merged_rows(
            connection, columns, temporary_path, parent_member_types
        )
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output_rows


def _write_merged_rows(
    connection: sqlite3.Connection,
    columns: Sequence[str],
    output_path: Path,
    parent_member_types: dict[str, str],
) -> int:
    id_index = columns.index(KEY_COLUMNS[0])
    date_index = columns.index(KEY_COLUMNS[1])
    selected_columns = ", ".join(f'"c{index}"' for index in range(len(columns)))
    cursor = connection.execute(
        f"SELECT {selected_columns} FROM rows "
        f'ORDER BY "c{id_index}", "c{date_index}", completeness DESC, {selected_columns}'
    )

    output_rows = 0
    current_key: tuple[str, str] | None = None
    group_rows: list[list[str]] = []
    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.writer(output_file)
        writer.writerow(columns)
        for raw_row in cursor:
            row = list(raw_row)
            key = (row[id_index], row[date_index])
            if current_key is not None and key != current_key:
                output_rows += _write_merged_group(
                    writer, group_rows, columns, parent_member_types
                )
                group_rows = []
            current_key = key
            group_rows.append(row)

        output_rows += _write_merged_group(
            writer, group_rows, columns, parent_member_types
        )

    return output_rows


def _latest_parent_member_types(
    connection: sqlite3.Connection, columns: Sequence[str]
) -> dict[str, str]:
    """Find the most recently updated non-branch type for each company ID."""
    if "Member Type" not in columns:
        return {}
    id_index = columns.index("iMIS Id")
    type_index = columns.index("Member Type")
    date_index = columns.index("Last Updated")
    rows = connection.execute(
        f'SELECT "c{id_index}", "c{type_index}", "c{date_index}" FROM rows'
    )
    latest: dict[str, tuple[str, str]] = {}
    for imis_id, member_type, updated in rows:
        if not member_type or member_type.endswith("B"):
            continue
        if imis_id not in latest or _date_sort_key(updated) > latest[imis_id][0]:
            latest[imis_id] = (_date_sort_key(updated), member_type)
    return {imis_id: member_type for imis_id, (_, member_type) in latest.items()}


def _date_sort_key(value: str) -> str:
    """Make the iMIS month/day/year timestamp sortable without locale settings."""
    date_part, time_part, meridiem = value.split()
    if "/" in date_part:
        month, day, year = (int(part) for part in date_part.split("/"))
    else:
        year, month, day = (int(part) for part in date_part.split("-"))
    hour, minute, second = (int(part) for part in time_part.split(":"))
    if meridiem == "PM" and hour != 12:
        hour += 12
    elif meridiem == "AM" and hour == 12:
        hour = 0
    return f"{year:04d}{month:02d}{day:02d}{hour:02d}{minute:02d}{second:02d}"


def _write_merged_group(
    writer: csv.writer,
    rows: list[list[str]],
    columns: Sequence[str],
    parent_member_types: dict[str, str],
) -> int:
    _resolve_branch_member_type(rows, columns, parent_member_types)
    _resolve_former_member_type(rows, columns)
    _resolve_is_member(rows, columns)
    _resolve_company_member_type(rows, columns)
    _resolve_member_status(rows, columns)
    clusters: list[list[str]] = []
    for row in rows:
        _add_to_compatible_cluster(row, clusters, columns)
    return _write_clusters(writer, clusters)


def _resolve_branch_member_type(
    rows: list[list[str]],
    columns: Sequence[str],
    parent_member_types: dict[str, str],
) -> None:
    """Select the branch code when a conflicting group has a matching parent."""
    if "Major Key" not in columns or "Company Member Type" not in columns:
        return
    major_index = columns.index("Major Key")
    company_type_index = columns.index("Company Member Type")
    major_keys = {row[major_index] for row in rows if row[major_index]}
    options = {row[company_type_index] for row in rows if row[company_type_index]}
    if len(major_keys) != 1 or len(options) < 2:
        return
    parent_type = parent_member_types.get(major_keys.pop())
    expected_type = BRANCH_MEMBER_TYPES.get(parent_type)
    if expected_type not in options:
        return
    for row in rows:
        if row[company_type_index]:
            row[company_type_index] = expected_type


def _resolve_former_member_type(
    rows: list[list[str]], columns: Sequence[str]
) -> None:
    """Use a consistent membership flag to distinguish current and former types."""
    if "Company Member Type" not in columns or "Is Member" not in columns:
        return
    type_index = columns.index("Company Member Type")
    member_index = columns.index("Is Member")
    options = {row[type_index] for row in rows if row[type_index]}
    member_values = {row[member_index] for row in rows if row[member_index]}
    expected_by_options = {
        frozenset({"FPROF", "PROF"}): {"False": "FPROF", "True": "PROF"},
        frozenset({"AFF", "FAFF"}): {"False": "FAFF", "True": "AFF"},
    }
    expected_type = expected_by_options.get(frozenset(options), {}).get(
        next(iter(member_values), "")
    )
    if len(member_values) != 1 or expected_type is None:
        return
    for row in rows:
        if row[type_index]:
            row[type_index] = expected_type


def _resolve_is_member(rows: list[list[str]], columns: Sequence[str]) -> None:
    """Keep documented branch and dependent member types marked as members."""
    if "Member Type" not in columns or "Is Member" not in columns:
        return
    type_index = columns.index("Member Type")
    member_index = columns.index("Is Member")
    member_types = {row[type_index] for row in rows if row[type_index]}
    member_values = {row[member_index] for row in rows if row[member_index]}
    if (
        member_values != {"False", "True"}
        or not member_types
        or not member_types <= MEMBER_TYPES_WITH_IS_MEMBER_TRUE
    ):
        return
    for row in rows:
        if row[member_index]:
            row[member_index] = "True"


def _resolve_company_member_type(
    rows: list[list[str]], columns: Sequence[str]
) -> None:
    """Resolve a company type when the contact's member type specifies it."""
    if "Member Type" not in columns or "Company Member Type" not in columns:
        return
    member_type_index = columns.index("Member Type")
    company_type_index = columns.index("Company Member Type")
    member_types = {row[member_type_index] for row in rows if row[member_type_index]}
    options = {row[company_type_index] for row in rows if row[company_type_index]}
    expected_types = {
        COMPANY_MEMBER_TYPE_BY_MEMBER_TYPE[member_type]
        for member_type in member_types
        if member_type in COMPANY_MEMBER_TYPE_BY_MEMBER_TYPE
    }
    if len(options) < 2 or len(expected_types) != 1:
        return
    expected_type = expected_types.pop()
    if expected_type not in options:
        return
    for row in rows:
        if row[company_type_index]:
            row[company_type_index] = expected_type


def _resolve_member_status(rows: list[list[str]], columns: Sequence[str]) -> None:
    """Resolve 2026 New/Renewed conflicts from the company's join date."""
    required_columns = {"Last Updated", "Join Date", "Member Status"}
    if not required_columns <= set(columns):
        return
    date_index = columns.index("Last Updated")
    join_date_index = columns.index("Join Date")
    status_index = columns.index("Member Status")
    statuses = {row[status_index] for row in rows if row[status_index]}
    join_dates = {row[join_date_index] for row in rows if row[join_date_index]}
    if statuses != {"New", "Renewed"} or len(join_dates) != 1:
        return
    record_date = _date_from_value(rows[0][date_index])
    if record_date is None or record_date.year != 2026:
        return
    join_date = _date_from_value(join_dates.pop())
    if join_date is None:
        return
    # A join date within 90 days of the record is treated as a new membership.
    expected_status = "New" if (record_date - join_date).days <= 90 else "Renewed"
    for row in rows:
        if row[status_index]:
            row[status_index] = expected_status


def _date_from_value(value: str) -> date | None:
    """Return a date from an iMIS date or timestamp value."""
    date_part = value.split(maxsplit=1)[0]
    separator = "/" if "/" in date_part else "-"
    try:
        first, second, third = (int(part) for part in date_part.split(separator))
    except ValueError:
        return None
    if separator == "/":
        return date(third, first, second)
    return date(first, second, third)


def _add_to_compatible_cluster(
    row: list[str], clusters: list[list[str]], columns: Sequence[str]
) -> None:
    for cluster in clusters:
        if _rows_are_compatible(cluster, row, columns):
            for index, value in enumerate(row):
                if not cluster[index] and value:
                    cluster[index] = value
            return
    clusters.append(row)


def _rows_are_compatible(
    left: Sequence[str], right: Sequence[str], columns: Sequence[str]
) -> bool:
    return all(
        not left_value
        or not right_value
        or left_value == right_value
        for column, left_value, right_value in zip(
            columns, left, right, strict=True
        )
    )


def _clean_value(column: str, value: str) -> str:
    """Return a consistent display value for harmless export-format differences."""
    cleaned = re.sub(r"\r+\n", "\n", value.strip()).replace("\r", "\n")
    if column == "Country" and cleaned.casefold() == "czech republic":
        return "Czechia"
    if column == "Company":
        return PREFERRED_COMPANY_NAMES.get(cleaned, cleaned)
    return cleaned


def _write_clusters(writer: csv.writer, clusters: Iterable[list[str]]) -> int:
    rows = list(clusters)
    writer.writerows(rows)
    return len(rows)
