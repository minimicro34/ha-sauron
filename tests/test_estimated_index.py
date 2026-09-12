"""Tests for the cumulative estimated water index helpers."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.sauron.coordinator import (
    _estimate_index_from_monthly,
    _iter_months,
)


def _month(*entries: tuple[str, float]) -> dict[str, object]:
    return {
        "consumptions": [
            {"startDate": day, "value": value, "rangeType": "Day"}
            for day, value in entries
        ]
    }


def test_iter_months_crosses_year_boundary() -> None:
    assert _iter_months(date(2026, 11, 15), date(2027, 2, 3)) == [
        (2026, 11),
        (2026, 12),
        (2027, 1),
        (2027, 2),
    ]


def test_mid_month_physical_reading_excludes_reading_day() -> None:
    result = _estimate_index_from_monthly(
        315.000,
        date(2026, 5, 28),
        date(2026, 5, 31),
        [
            _month(
                ("2026-05-28T00:00:00", 0.900),
                ("2026-05-29T00:00:00", 0.100),
                ("2026-05-30T00:00:00", 0.200),
                ("2026-05-31T00:00:00", 0.300),
            )
        ],
    )
    assert result == pytest.approx(315.600, abs=0.001)


def test_reconstructs_across_multiple_months() -> None:
    result = _estimate_index_from_monthly(
        315.000,
        date(2026, 5, 28),
        date(2026, 7, 2),
        [
            _month(
                ("2026-05-29T00:00:00", 0.100),
                ("2026-05-30T00:00:00", 0.200),
            ),
            _month(
                ("2026-06-01T00:00:00", 1.000),
                ("2026-06-15T00:00:00", 2.000),
            ),
            _month(
                ("2026-07-01T00:00:00", 0.400),
                ("2026-07-02T00:00:00", 0.500),
                ("2026-07-03T00:00:00", 9.999),
            ),
        ],
    )
    assert result == pytest.approx(319.200, abs=0.001)


def test_zero_consumption_days_are_valid() -> None:
    result = _estimate_index_from_monthly(
        100.000,
        date(2026, 8, 1),
        date(2026, 8, 3),
        [
            _month(
                ("2026-08-02T00:00:00", 0.000),
                ("2026-08-03T00:00:00", 0.125),
            )
        ],
    )
    assert result == pytest.approx(100.125, abs=0.001)


def test_new_physical_reading_rebases_estimate() -> None:
    """A technician reading becomes the new baseline; older usage is ignored."""
    result = _estimate_index_from_monthly(
        350.000,
        date(2026, 11, 15),
        date(2026, 11, 17),
        [
            _month(
                ("2026-11-14T00:00:00", 4.000),
                ("2026-11-15T00:00:00", 3.000),
                ("2026-11-16T00:00:00", 0.250),
                ("2026-11-17T00:00:00", 0.500),
            )
        ],
    )
    assert result == pytest.approx(350.750, abs=0.001)


def test_invalid_monthly_payload_makes_estimate_unavailable() -> None:
    assert (
        _estimate_index_from_monthly(
            315.000,
            date(2026, 5, 28),
            date(2026, 5, 29),
            [{"unexpected": []}],
        )
        is None
    )


def test_no_days_after_reading_returns_physical_index() -> None:
    result = _estimate_index_from_monthly(
        315.000,
        date(2026, 5, 28),
        date(2026, 5, 28),
        [],
    )
    assert result == pytest.approx(315.000, abs=0.001)
