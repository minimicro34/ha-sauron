"""Regression tests for delayed SAUR readings in the previous ISO week."""

from datetime import date

from custom_components.sauron.coordinator import (
    _extract_week_total_from_monthly,
    _iter_months,
)


def test_delayed_sunday_consumption_is_counted_in_previous_week() -> None:
    """SAUR can publish Sunday's reading on Tuesday of the next week."""
    readings = [0.11, 0.09, 0.14, 0.09, 0.04, 0.06, 0.90]
    raw = {
        "consumptions": [
            {
                "rangeType": "Day",
                "startDate": f"2026-10-{day:02d}T00:00:00",
                "value": value,
            }
            for day, value in zip(range(5, 12), readings, strict=True)
        ]
    }
    assert _extract_week_total_from_monthly(raw, date(2026, 10, 11)) == 1.43
    assert _extract_week_total_from_monthly(raw, date(2026, 10, 12)) is None


def test_previous_week_can_span_two_months() -> None:
    assert _iter_months(date(2026, 9, 28), date(2026, 10, 4)) == [
        (2026, 9),
        (2026, 10),
    ]
