"""Tests for aggregate-only membership lifecycle evidence discovery."""

import csv
import importlib.util
from pathlib import Path

import pytest

from aisc_imis.lifecycle_discovery import (
    LifecycleDiscoveryError,
    LifecycleField,
    LifecycleSource,
    UsefulCombination,
    build_lifecycle_profile,
    render_markdown,
    write_evidence_matrix,
)


def write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def source(path: Path) -> LifecycleSource:
    return LifecycleSource(
        "Synthetic changes",
        path,
        (
            LifecycleField(
                "Change Type", "lifecycle-event candidate", "possible inference"
            ),
            LifecycleField("Status", "state observation", "direct fact"),
            LifecycleField("Paid Through", "payment activity", "direct fact"),
            LifecycleField(
                "A_Transaction", "metadata", "direct fact", publish_values=False
            ),
        ),
        (UsefulCombination("Change type by status", ("Change Type", "Status"), 2),),
    )


def test_counts_distinct_codes_blanks_and_bounded_combinations(tmp_path):
    path = tmp_path / "changes.csv"
    write_csv(
        path,
        ["Change Type", "Status", "Paid Through", "A_Transaction", "Member ID"],
        [
            {
                "Change Type": "JOIN",
                "Status": "A",
                "Paid Through": "2027",
                "A_Transaction": "T-1",
                "Member ID": "1",
            },
            {
                "Change Type": "JOIN",
                "Status": "A",
                "Paid Through": "",
                "A_Transaction": "T-2",
                "Member ID": "2",
            },
            {
                "Change Type": "REIN",
                "Status": "I",
                "Paid Through": "2028",
                "A_Transaction": "T-3",
                "Member ID": "3",
            },
            {
                "Change Type": "",
                "Status": "I",
                "Paid Through": "",
                "A_Transaction": "T-3",
                "Member ID": "4",
            },
            {
                "Change Type": "OTHER",
                "Status": "A",
                "Paid Through": "",
                "A_Transaction": "T-4",
                "Member ID": "5",
            },
        ],
    )

    result = build_lifecycle_profile([source(path)]).sources[0]

    assert result.fields["Change Type"].distinct_values == 3
    assert result.fields["Change Type"].blank_rows == 1
    assert result.fields["Paid Through"].distinct_values == 2
    assert result.fields["A_Transaction"].distinct_values == 4
    assert result.combinations[0].rows == (("JOIN", "A", 2), ("OTHER", "A", 1))
    assert result.combinations[0].omitted_rows == 1


def test_rendering_separates_facts_observations_and_inferences_and_is_private(tmp_path):
    path = tmp_path / "private.csv"
    write_csv(
        path,
        [
            "Change Type",
            "Status",
            "Paid Through",
            "A_Transaction",
            "Member ID",
            "Name",
            "Notes",
        ],
        [
            {
                "Change Type": "JOIN",
                "Status": "A",
                "Paid Through": "2027",
                "A_Transaction": "secret-tx",
                "Member ID": "9988",
                "Name": "Ada",
                "Notes": "private note",
            }
        ],
    )

    markdown = render_markdown(build_lifecycle_profile([source(path)]))

    assert "Direct facts" in markdown
    assert "State observations" in markdown
    assert "Possible inferences" in markdown
    assert "payment activity" in markdown
    assert "countable-status transition" in markdown
    for private_value in ("secret-tx", "9988", "Ada", "private note"):
        assert private_value not in markdown


def test_matrix_defaults_and_preserves_human_reviewed_mappings(tmp_path):
    path = tmp_path / "changes.csv"
    output = tmp_path / "taxonomy.csv"
    write_csv(
        path,
        ["Change Type", "Status", "Paid Through", "A_Transaction"],
        [
            {
                "Change Type": "JOIN",
                "Status": "A",
                "Paid Through": "2027",
                "A_Transaction": "T-1",
            }
        ],
    )
    profile = build_lifecycle_profile([source(path)])

    write_evidence_matrix(profile, output)
    with output.open(newline="") as input_file:
        rows = list(csv.DictReader(input_file))
    change_row = next(row for row in rows if row["field"] == "Change Type")
    payment_row = next(row for row in rows if row["field"] == "Paid Through")
    assert change_row["draft_lifecycle_name"] == "unknown"
    assert change_row["countability_effect"] == "unresolved"
    assert payment_row["evidence_class"] == "payment activity"
    assert payment_row["countability_effect"] == "unresolved"
    assert all(row["code"] != "T-1" for row in rows)

    change_row["draft_lifecycle_name"] = "joined"
    change_row["countability_effect"] = "review required"
    change_row["review_note"] = "Confirmed in source system."
    with output.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    write_evidence_matrix(profile, output)
    with output.open(newline="") as input_file:
        revised = list(csv.DictReader(input_file))
    preserved = next(row for row in revised if row["field"] == "Change Type")
    assert preserved["draft_lifecycle_name"] == "joined"
    assert preserved["countability_effect"] == "review required"
    assert preserved["review_note"] == "Confirmed in source system."


def test_fails_clearly_for_missing_files_and_columns(tmp_path):
    with pytest.raises(LifecycleDiscoveryError, match="does not exist"):
        build_lifecycle_profile([source(tmp_path / "missing.csv")])

    path = tmp_path / "incomplete.csv"
    write_csv(path, ["Change Type"], [{"Change Type": "JOIN"}])
    with pytest.raises(LifecycleDiscoveryError, match="missing configured columns"):
        build_lifecycle_profile([source(path)])


def test_generator_keeps_untrusted_activity_fields_aggregate_only():
    script_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "generate_membership_lifecycle_taxonomy.py"
    )
    spec = importlib.util.spec_from_file_location("lifecycle_generator", script_path)
    assert spec is not None and spec.loader is not None
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)

    activity = next(
        source
        for source in generator.default_sources()
        if source.name == "Activity history"
    )
    fields = {field.column: field for field in activity.fields}
    untrusted = (
        "A_Transaction",
        "Action Codes",
        "Other Code",
        "Product Code",
        "Source Code",
    )
    assert all(not fields[column].publish_values for column in untrusted)
    assert all(
        column not in activity.combinations[0].columns for column in untrusted[1:]
    )
