"""Dated SAUR Recorder statistics tests."""

from datetime import UTC, date, datetime

import pytest

from custom_components.sauron.statistics import build_daily_statistics


def _payload(*values: tuple[str, float]) -> dict:
    return {
        "consumptions": [
            {"rangeType": "Day", "startDate": day, "value": value} for day, value in values
        ]
    }


def test_late_publication_uses_consumption_date() -> None:
    rows = build_daily_statistics(
        [_payload(("2026-10-11", 0.9), ("2026-10-12", 0.77))],
        date(2026, 5, 28),
        date(2026, 10, 13),
        "Europe/Paris",
    )
    assert [row["sum"] for row in rows] == [0.9, 1.67]
    assert rows[0]["start"] == datetime(2026, 10, 10, 22, tzinfo=UTC)
    assert rows[1]["start"] == datetime(2026, 10, 11, 22, tzinfo=UTC)


def test_corrected_day_recomputes_all_later_sums() -> None:
    initial = build_daily_statistics(
        [_payload(("2026-10-11", 0.5), ("2026-10-12", 0.77))],
        date(2026, 10, 10),
        date(2026, 10, 12),
        "Europe/Paris",
    )
    corrected = build_daily_statistics(
        [_payload(("2026-10-11", 0.9), ("2026-10-12", 0.77))],
        date(2026, 10, 10),
        date(2026, 10, 12),
        "Europe/Paris",
    )
    assert [row["sum"] for row in initial] == [0.5, 1.27]
    assert [row["sum"] for row in corrected] == [0.9, 1.67]


def test_missing_days_are_not_inserted_as_zero() -> None:
    rows = build_daily_statistics(
        [_payload(("2026-10-11", 0.9), ("2026-10-13", 0.2))],
        date(2026, 10, 10),
        date(2026, 10, 13),
        "Europe/Paris",
    )
    assert len(rows) == 2
    assert rows[-1]["sum"] == 1.1


def test_reject_negative_consumption() -> None:
    with pytest.raises(ValueError, match="Invalid SAUR daily volume"):
        build_daily_statistics(
            [_payload(("2026-10-11", -0.2))],
            date(2026, 10, 10),
            date(2026, 10, 11),
            "Europe/Paris",
        )


def test_month_boundary_and_repeated_month_payloads() -> None:
    rows = build_daily_statistics(
        [
            _payload(("2026-09-30", 0.1)),
            _payload(("2026-10-01", 0.2)),
        ],
        date(2026, 9, 29),
        date(2026, 10, 1),
        "Europe/Paris",
    )
    assert [row["sum"] for row in rows] == [0.1, 0.3]
