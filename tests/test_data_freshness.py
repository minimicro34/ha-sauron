"""Tests for SAURon data freshness semantics."""

from __future__ import annotations

from datetime import UTC, date, datetime

from custom_components.sauron.const import DEFAULT_STALE_DATA_THRESHOLD_H
from custom_components.sauron.coordinator import _data_age_hours


def test_data_age_uses_latest_daily_date() -> None:
    now = datetime(2026, 9, 14, 21, 30, tzinfo=UTC)

    assert _data_age_hours(date(2026, 9, 14), now) == 21.5
    assert _data_age_hours(date(2026, 9, 13), now) == 45.5


def test_data_age_is_none_without_daily_date() -> None:
    now = datetime(2026, 9, 14, 21, 30, tzinfo=UTC)

    assert _data_age_hours(None, now) is None


def test_data_age_never_goes_negative() -> None:
    now = datetime(2026, 9, 14, 21, 30, tzinfo=UTC)

    assert _data_age_hours(date(2026, 9, 15), now) == 0.0


def test_default_stale_threshold_allows_weekend_delay() -> None:
    assert DEFAULT_STALE_DATA_THRESHOLD_H == 72
