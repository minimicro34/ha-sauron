"""Dated SAUR Recorder statistics tests."""

from datetime import UTC, date, datetime

import pytest

from custom_components.sauron.statistics import (
    build_daily_statistics,
    build_ledger_statistics,
    merge_daily_history,
)


def _payload(*values: tuple[str, float]) -> dict:
    return {
        "consumptions": [
            {"rangeType": "Day", "startDate": day, "value": value} for day, value in values
        ]
    }


def test_late_publication_uses_consumption_date() -> None:
    rows = build_daily_statistics(
        [_payload(("2026-10-11", 0.9), ("2026-10-12", 0.77))],
        date(2026, 10, 10),
        date(2026, 10, 13),
        "Europe/Paris",
    )
    assert [row["sum"] for row in rows] == [0.9, 1.67]
    assert rows[0]["start"] == datetime(2026, 10, 11, 21, tzinfo=UTC)
    assert rows[1]["start"] == datetime(2026, 10, 12, 21, tzinfo=UTC)


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


def test_missing_days_prevent_partial_cumulative_import() -> None:
    with pytest.raises(ValueError, match="Incomplete SAUR daily history"):
        build_daily_statistics(
            [_payload(("2026-10-11", 0.9), ("2026-10-13", 0.2))],
            date(2026, 10, 10),
            date(2026, 10, 13),
            "Europe/Paris",
        )


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


def test_winter_time_uses_correct_utc_hour() -> None:
    rows = build_daily_statistics(
        [_payload(("2026-12-01", 0.2))],
        date(2026, 11, 30),
        date(2026, 12, 1),
        "Europe/Paris",
    )
    assert rows[0]["start"] == datetime(2026, 12, 1, 22, tzinfo=UTC)


def test_missing_first_day_prevents_partial_import() -> None:
    with pytest.raises(ValueError, match="Incomplete SAUR daily history"):
        build_daily_statistics(
            [_payload(("2026-10-12", 0.2))],
            date(2026, 10, 10),
            date(2026, 10, 12),
            "Europe/Paris",
        )


def test_new_physical_reading_keeps_previous_cumulative_sum() -> None:
    rows = build_daily_statistics(
        [_payload(("2026-10-11", 0.2), ("2026-10-12", 0.3))],
        date(2026, 10, 10),
        date(2026, 10, 12),
        "Europe/Paris",
        initial_sum=120.5,
    )
    assert [row["sum"] for row in rows] == [120.7, 121.0]


def test_invalid_cumulative_baseline_is_rejected() -> None:
    with pytest.raises(ValueError, match="Invalid initial cumulative sum"):
        build_daily_statistics(
            [_payload(("2026-10-11", 0.2))],
            date(2026, 10, 10),
            date(2026, 10, 11),
            "Europe/Paris",
            initial_sum=float("nan"),
        )


def test_corrected_day_recalculates_later_sums() -> None:
    existing = {"2026-10-11": 0.9, "2026-10-12": 0.2}
    updated = merge_daily_history(
        existing,
        [_payload(("2026-10-11", 1.1), ("2026-10-12", 0.2))],
        date(2026, 10, 10),
        date(2026, 10, 12),
    )
    assert updated["2026-10-11"] == 1.1
    assert [row["sum"] for row in build_ledger_statistics(updated, "UTC")] == [
        1.1,
        1.3,
    ]


def test_correction_does_not_erase_unreturned_existing_days() -> None:
    existing = {"2026-10-11": 0.9, "2026-10-12": 0.2}
    assert merge_daily_history(
        existing, [_payload(("2026-10-12", 0.2))],
        date(2026, 10, 10), date(2026, 10, 12),
    ) == existing


def test_empty_daily_ledger_produces_no_recorder_rows():
    assert build_ledger_statistics({}, "UTC") == []


@pytest.mark.parametrize("bad", [{}, {"consumptions": [{"rangeType": "Day", "value": 0.2}]}])
def test_malformed_recorder_monthly_readings_are_rejected(bad):
    with pytest.raises(ValueError, match="Invalid SAUR"):
        build_daily_statistics(
            [bad], date(2026, 10, 10), date(2026, 10, 11), "UTC"
        )


def test_conflicting_monthly_recorder_readings_are_rejected():
    with pytest.raises(ValueError, match="Conflicting SAUR readings"):
        build_daily_statistics(
            [_payload(("2026-10-11", 0.2)), _payload(("2026-10-11", 0.3))],
            date(2026, 10, 10), date(2026, 10, 11), "UTC",
        )


@pytest.mark.parametrize("value", [-0.1, float("nan"), float("inf")])
def test_ledger_merge_rejects_invalid_late_corrections(value):
    ledger = {"2026-10-11": 0.9, "2026-10-12": 0.2}
    with pytest.raises(ValueError, match="Invalid SAUR daily volume"):
        merge_daily_history(
            ledger, [_payload(("2026-10-12", value))],
            date(2026, 10, 10), date(2026, 10, 12),
        )
    assert ledger == {"2026-10-11": 0.9, "2026-10-12": 0.2}
