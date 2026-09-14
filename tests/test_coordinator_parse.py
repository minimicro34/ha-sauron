"""Tests for the coordinator parse helpers (pure-library, no HA)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from custom_components.sauron.api.exceptions import SauronNoDataError
from custom_components.sauron.coordinator import (
    _extract_daily_liters,
    _extract_latest_daily,
    _extract_period_m3,
    _extract_week_total_m3,
    _parse_consumption,
    _parse_last_index,
)

_NOW = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)
_SUB = "100030690002033754"


class TestParseLastIndex:
    """Tests for the real /meter_indexes/last parser."""

    def test_nominal(self) -> None:
        raw = {"readingDate": "2026-06-15T00:00:00", "indexValue": 1234.567}
        data = _parse_last_index(_SUB, raw, _NOW)
        assert data.latest_reading.value_m3 == 1234.567
        assert str(data.latest_reading.reading_date) == "2026-06-15"

    def test_missing_index_value_raises(self) -> None:
        with pytest.raises(SauronNoDataError, match="indexValue missing"):
            _parse_last_index(_SUB, {"readingDate": "2026-06-15"}, _NOW)

    def test_non_dict_raises(self) -> None:
        with pytest.raises(SauronNoDataError):
            _parse_last_index(_SUB, [], _NOW)  # type: ignore[arg-type]

    def test_bad_date_falls_back_to_fetched_at(self) -> None:
        raw = {"indexValue": 100.0, "readingDate": "not-a-date"}
        data = _parse_last_index(_SUB, raw, _NOW)
        assert data.latest_reading.reading_date == _NOW.date()

    def test_integer_index_value(self) -> None:
        raw = {"readingDate": "2026-06-15", "indexValue": 2000}
        data = _parse_last_index(_SUB, raw, _NOW)
        assert data.latest_reading.value_m3 == 2000.0


class TestExtractDailyLiters:
    """Tests for the monthly consumptions daily extractor."""

    def test_extracts_last_day_entry(self) -> None:
        raw = {
            "consumptions": [
                {
                    "startDate": "2026-06-14 00:00:00",
                    "value": 0.072,
                    "rangeType": "Day",
                },
                {
                    "startDate": "2026-06-15 00:00:00",
                    "value": 0.085,
                    "rangeType": "Day",
                },
            ]
        }
        assert _extract_daily_liters(raw) == pytest.approx(85.0, abs=0.5)

    def test_uses_latest_date_even_if_payload_is_unsorted(self) -> None:
        raw = {
            "consumptions": [
                {
                    "startDate": "2026-06-15 00:00:00",
                    "value": 0.085,
                    "rangeType": "Day",
                },
                {
                    "startDate": "2026-06-13 00:00:00",
                    "value": 0.400,
                    "rangeType": "Day",
                },
            ]
        }
        assert _extract_daily_liters(raw) == pytest.approx(85.0, abs=0.5)

    def test_returns_latest_daily_date_with_value(self) -> None:
        raw = {
            "consumptions": [
                {
                    "startDate": "2026-06-12 00:00:00",
                    "value": 0.150,
                    "rangeType": "Day",
                },
                {
                    "startDate": "2026-06-15 00:00:00",
                    "value": 0.085,
                    "rangeType": "Day",
                },
                {
                    "startDate": "2026-06-16 00:00:00",
                    "value": 0.0,
                    "rangeType": "Day",
                },
            ]
        }
        liters, daily_date = _extract_latest_daily(raw)
        assert liters == pytest.approx(85.0, abs=0.5)
        assert daily_date == date(2026, 6, 15)

    def test_ignores_non_day_entries(self) -> None:
        raw = {
            "consumptions": [
                {"startDate": "2026-W24", "value": 0.612, "rangeType": "Week"},
            ]
        }
        assert _extract_daily_liters(raw) is None

    def test_negative_value_returns_none(self) -> None:
        raw = {
            "consumptions": [
                {
                    "startDate": "2026-06-15 00:00:00",
                    "value": -0.1,
                    "rangeType": "Day",
                },
            ]
        }
        assert _extract_daily_liters(raw) is None

    def test_empty_consumptions(self) -> None:
        assert _extract_daily_liters({"consumptions": []}) is None
        assert _extract_latest_daily({"consumptions": []}) == (None, None)

    def test_missing_consumptions_key(self) -> None:
        assert _extract_daily_liters({}) is None

    def test_converts_m3_to_liters(self) -> None:
        raw = {
            "consumptions": [
                {
                    "startDate": "2026-06-15 00:00:00",
                    "value": 0.150,
                    "rangeType": "Day",
                },
            ]
        }
        assert _extract_daily_liters(raw) == pytest.approx(150.0, abs=0.5)


class TestParseConsumptionList:
    """Legacy list-based parser (kept for backward compat with existing tests)."""

    def test_single_entry_list(self) -> None:
        raw = [{"index": 1234.567, "date": "2026-06-15"}]
        data = _parse_consumption(_SUB, raw, _NOW)
        assert data.latest_reading.value_m3 == 1234.567
        assert str(data.latest_reading.reading_date) == "2026-06-15"
        assert data.daily_liters is None

    def test_two_entries_computes_daily(self) -> None:
        raw = [
            {"index": 1233.000, "date": "2026-06-14"},
            {"index": 1234.567, "date": "2026-06-15"},
        ]
        data = _parse_consumption(_SUB, raw, _NOW)
        assert data.daily_liters == pytest.approx(1567.0, abs=1.0)

    def test_negative_delta_ignored(self) -> None:
        raw = [
            {"index": 1234.567, "date": "2026-06-14"},
            {"index": 100.000, "date": "2026-06-15"},
        ]
        data = _parse_consumption(_SUB, raw, _NOW)
        assert data.daily_liters is None

    def test_uses_last_entry_as_latest(self) -> None:
        raw = [
            {"index": 100.0, "date": "2026-06-13"},
            {"index": 101.0, "date": "2026-06-14"},
            {"index": 102.5, "date": "2026-06-15"},
        ]
        data = _parse_consumption(_SUB, raw, _NOW)
        assert data.latest_reading.value_m3 == 102.5
        assert data.daily_liters == pytest.approx(1500.0, abs=1.0)


class TestParseConsumptionDict:
    def test_dict_with_pre_computed_daily(self) -> None:
        raw = {
            "index": 1234.567,
            "date": "2026-06-15",
            "dailyConsumption": 0.085,
        }
        data = _parse_consumption(_SUB, raw, _NOW)
        assert data.daily_liters == pytest.approx(85.0, abs=0.5)

    def test_dict_without_daily(self) -> None:
        raw = {"index": 1234.567, "date": "2026-06-15"}
        data = _parse_consumption(_SUB, raw, _NOW)
        assert data.daily_liters is None

    def test_dict_fallback_date_from_fetched_at(self) -> None:
        raw = {"value": 500.0}
        data = _parse_consumption(_SUB, raw, _NOW)
        assert data.latest_reading.reading_date == _NOW.date()

    def test_dict_alternative_field_names(self) -> None:
        raw = {"volume": 999.9, "dateRelevee": "2026-06-10"}
        data = _parse_consumption(_SUB, raw, _NOW)
        assert data.latest_reading.value_m3 == 999.9
        assert str(data.latest_reading.reading_date) == "2026-06-10"


class TestParseConsumptionErrors:
    def test_empty_list_raises(self) -> None:
        with pytest.raises(SauronNoDataError):
            _parse_consumption(_SUB, [], _NOW)

    def test_non_list_non_dict_raises(self) -> None:
        with pytest.raises(SauronNoDataError):
            _parse_consumption(_SUB, None, _NOW)  # type: ignore[arg-type]


class TestExtractWeekTotalM3:
    def test_sums_all_day_entries(self) -> None:
        raw = {
            "consumptions": [
                {
                    "startDate": "2026-06-10 00:00:00",
                    "value": 0.080,
                    "rangeType": "Day",
                },
                {
                    "startDate": "2026-06-11 00:00:00",
                    "value": 0.090,
                    "rangeType": "Day",
                },
                {
                    "startDate": "2026-06-12 00:00:00",
                    "value": 0.072,
                    "rangeType": "Day",
                },
            ]
        }
        result = _extract_week_total_m3(raw)
        assert result == pytest.approx(0.242, abs=0.001)

    def test_ignores_non_day_entries(self) -> None:
        raw = {"consumptions": [{"value": 1.5, "rangeType": "Week"}]}
        assert _extract_week_total_m3(raw) is None

    def test_empty_returns_none(self) -> None:
        assert _extract_week_total_m3({}) is None


class TestExtractPeriodM3:
    def test_sums_consumptions_list(self) -> None:
        raw = {
            "consumptions": [
                {"value": 2.5, "rangeType": "Month"},
                {"value": 3.1, "rangeType": "Month"},
            ]
        }
        result = _extract_period_m3(raw)
        assert result == pytest.approx(5.6, abs=0.001)

    def test_single_value_fallback(self) -> None:
        raw = {"total": 18.5}
        assert _extract_period_m3(raw) == pytest.approx(18.5, abs=0.001)

    def test_empty_consumptions_uses_value_key(self) -> None:
        raw = {"consumptions": [], "value": 12.3}
        assert _extract_period_m3(raw) == pytest.approx(12.3, abs=0.001)

    def test_all_negative_returns_zero(self) -> None:
        raw = {"consumptions": [{"value": -1.0}, {"value": -2.0}]}
        assert _extract_period_m3(raw) == pytest.approx(0.0, abs=0.001)

    def test_no_data_returns_none(self) -> None:
        assert _extract_period_m3({}) is None
