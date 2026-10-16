"""Aggregate M1 membership numbers with explicit uncertainty."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from aisc_imis.board_adjusted_membership import BoardAdjustedMembershipView
from aisc_imis.period_membership_balance import (
    MembershipBalanceLine,
    PeriodMembershipBalance,
)


@dataclass(frozen=True)
class M1Row:
    """One overall or source Category M1 equation."""

    start_date: date
    end_date: date
    operational_as_of_date: date
    board_cutoff: date
    category: str | None
    operational_opening: int | None
    joined: int
    reinstated: int
    resigned: int
    expelled: int
    exited: int
    transfers_in: int
    transfers_out: int
    reviewed_adjustments: int
    operational_expected_closing: int | None
    operational_closing: int | None
    operational_difference: int | None
    board_opening_adjustment: int
    board_closing_adjustment: int
    board_adjustment_change: int
    board_adjusted_opening: int | None
    board_adjusted_expected_closing: int | None
    board_adjusted_closing: int | None
    board_adjusted_difference: int | None
    status: str


@dataclass(frozen=True)
class M1MembershipNumbers:
    start_date: date
    end_date: date
    operational_as_of_date: date
    board_cutoff: date
    overall: M1Row
    categories: dict[str, M1Row]


def build_m1_membership_numbers(
    balance: PeriodMembershipBalance,
    opening_board: BoardAdjustedMembershipView,
    closing_board: BoardAdjustedMembershipView,
    board_cutoff: date,
) -> M1MembershipNumbers:
    """Combine an operational period balance with two dated Board views.

    The period is half-open. Board adjustments are signed differences from the
    operational views; a balance difference is never promoted to an adjustment.
    """
    if balance.end_date <= balance.start_date:
        raise ValueError("M1 requires a nonempty period.")
    as_of = balance.end_date - timedelta(days=1)
    if board_cutoff < as_of:
        raise ValueError("Board cutoff must cover the operational as-of date.")
    if (
        opening_board.operational.as_of_date != balance.start_date - timedelta(days=1)
        or closing_board.operational.as_of_date != as_of
        or opening_board.board_cutoff != board_cutoff
        or closing_board.board_cutoff != board_cutoff
    ):
        raise ValueError("Board view dates and cutoffs must match the M1 period.")
    codes = tuple(balance.categories)
    if (
        set(opening_board.operational.categories) != set(codes)
        or set(closing_board.operational.categories) != set(codes)
        or set(opening_board.adjusted.categories) != set(codes)
        or set(closing_board.adjusted.categories) != set(codes)
    ):
        raise ValueError("Board views and balance must use the same Categories.")

    def row(category: str | None, line: MembershipBalanceLine) -> M1Row:
        opening = (
            opening_board.operational.overall
            if category is None
            else opening_board.operational.categories[category]
        )
        closing = (
            closing_board.operational.overall
            if category is None
            else closing_board.operational.categories[category]
        )
        opening_adjusted = (
            opening_board.adjusted.overall
            if category is None
            else opening_board.adjusted.categories[category]
        )
        closing_adjusted = (
            closing_board.adjusted.overall
            if category is None
            else closing_board.adjusted.categories[category]
        )
        opening_adjustment = (
            opening_board.adjustments.overall
            if category is None
            else opening_board.adjustments.categories[category]
        )
        closing_adjustment = (
            closing_board.adjustments.overall
            if category is None
            else closing_board.adjustments.categories[category]
        )
        if (opening.total is not None and opening.total != line.opening) or (
            closing.total is not None and closing.total != line.closing
        ):
            raise ValueError(
                "Operational Board views must match the period balance: "
                f"{category}: {(opening.total, closing.total)} != "
                f"{(line.opening, line.closing)}."
            )
        change = closing_adjustment - opening_adjustment

        def adjusted_total(
            operational_total: int | None,
            adjusted_view_total: int | None,
            confirmed_count: int,
            adjustment: int,
            view_operational_total: int | None,
            board_view: BoardAdjustedMembershipView,
        ) -> int | None:
            if operational_total is None:
                return None
            if adjusted_view_total is not None:
                return adjusted_view_total
            if category is not None and any(
                member.category not in codes
                for member in board_view.adjusted.overall.contributors
            ):
                return None
            # A short opening view can lack its own prior baseline. The period
            # balance supplies that baseline, provided the confirmed counts agree.
            if (
                view_operational_total is None
                and confirmed_count == operational_total + adjustment
            ):
                return operational_total + adjustment
            return None

        board_opening = adjusted_total(
            line.opening,
            opening_adjusted.total,
            opening_adjusted.confirmed_count,
            opening_adjustment,
            opening.total,
            opening_board,
        )
        board_closing = adjusted_total(
            line.closing,
            closing_adjusted.total,
            closing_adjusted.confirmed_count,
            closing_adjustment,
            closing.total,
            closing_board,
        )
        expected = (
            None
            if line.expected_closing is None
            else line.expected_closing + closing_adjustment
        )
        board_difference = (
            None
            if expected is None or board_closing is None
            else board_closing - expected
        )
        unknown = any(
            value is None
            for value in (
                line.opening,
                line.closing,
                line.difference,
                board_opening,
                board_closing,
                board_difference,
            )
        )
        status = (
            "unresolved_unknown"
            if unknown
            else "unresolved_difference"
            if line.difference or board_difference
            else "reconciled"
        )
        return M1Row(
            balance.start_date,
            balance.end_date,
            as_of,
            board_cutoff,
            category,
            line.opening,
            line.movements["joined"],
            line.movements["reinstated"],
            line.movements["resigned"],
            line.movements["expelled"],
            line.movements["exited"],
            line.transfers_in,
            line.transfers_out,
            line.adjustments,
            line.expected_closing,
            line.closing,
            line.difference,
            opening_adjustment,
            closing_adjustment,
            change,
            board_opening,
            expected,
            board_closing,
            board_difference,
            status,
        )

    return M1MembershipNumbers(
        balance.start_date,
        balance.end_date,
        as_of,
        board_cutoff,
        row(None, balance.overall),
        {code: row(code, balance.categories[code]) for code in codes},
    )


def write_m1_csv(result: M1MembershipNumbers, path: str | Path) -> None:
    """Write one aggregate row per overall/Category equation; None is blank."""
    fieldnames = tuple(M1Row.__dataclass_fields__)
    with Path(path).open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for item in (result.overall, *result.categories.values()):
            values = asdict(item)
            writer.writerow(
                {key: "" if value is None else value for key, value in values.items()}
            )
