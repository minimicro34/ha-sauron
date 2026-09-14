"""Additional meaningful branch coverage for coordinator helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from custom_components.sauron.coordinator import (
    _data_age_hours,
    _estimate_index_from_monthly,
    _extract_latest_daily,
    _extract_period_m3,
    _extract_week_total_from_monthly,
    _extract_week_total_m3,
    _has_nonzero_day,
    _iter_months,
    _parse_delivery_points,
    _safe_float,
)


class TestDeliveryPointParsing:
    def test_parses_full_meter_metadata(self) -> None:
        info = _parse_delivery_points(
            "SUB001",
            {
                "geographicAddress": {"city": "Montpellier"},
                "meter": {
                    "serialNumber": "M123",
                    "installationDate": "2024-02-03T12:00:00",
                    "meterBrandCode": "ELSTER (MID)",
                    "meterModelCode": "tModele 156",
                    "meterDiameterCode": "15mm",
                    "pairingTechnologyCode": "TeleCoronis",
                },
            },
        )

        assert info.address == "Montpellier"
        assert info.meter_serial == "M123"
        assert info.installation_date == date(2024, 2, 3)
        assert info.meter_brand == "ELSTER"
        assert info.meter_model == "Modele 156"
        assert info.meter_diameter == "15mm"
        assert info.telereleve_tech == "TeleCoronis"

    def test_bad_installation_date_and_missing_metadata_are_safe(self) -> None:
        info = _parse_delivery_points("SUB001", {"meter": {"installationDate": "bad"}})

        assert info.installation_date is None
        assert info.address == ""
        assert info.meter_brand == ""
        assert info.meter_model == ""


class TestGenericHelpers:
    def test_safe_float_uses_default_on_bad_input(self) -> None:
        assert _safe_float("bad", 12.5) == 12.5
        assert _safe_float(None, 3.0) == 3.0

    def test_data_age_clamps_future_date_to_zero(self) -> None:
        now = datetime(2026, 9, 14, 12, tzinfo=UTC)
        assert _data_age_hours(date(2026, 9, 15), now) == 0.0

    def test_iter_months_handles_year_boundary_and_reverse_range(self) -> None:
        assert _iter_months(date(2025, 11, 30), date(2026, 2, 1)) == [
            (2025, 11),
            (2025, 12),
            (2026, 1),
            (2026, 2),
        ]
        assert _iter_months(date(2026, 2, 1), date(2026, 1, 1)) == []


class TestEstimatedIndexValidation:
    def test_returns_physical_index_when_range_does_not_advance(self) -> None:
        result = _estimate_index_from_monthly(12.3456, date(2026, 9, 14), date(2026, 9, 14), [])
        assert result == 12.346

    def test_rejects_non_list_consumptions(self) -> None:
        assert (
            _estimate_index_from_monthly(
                12.0,
                date(2026, 9, 1),
                date(2026, 9, 2),
                [{"consumptions": "bad"}],
            )
            is None
        )

    def test_rejects_bad_required_date_value_and_negative_usage(self) -> None:
        assert (
            _estimate_index_from_monthly(
                12.0,
                date(2026, 9, 1),
                date(2026, 9, 2),
                [{"consumptions": [{"rangeType": "Day", "startDate": "bad", "value": 1}]}],
            )
            is None
        )
        assert (
            _estimate_index_from_monthly(
                12.0,
                date(2026, 9, 1),
                date(2026, 9, 2),
                [
                    {
                        "consumptions": [
                            {"rangeType": "Day", "startDate": "2026-09-02", "value": "bad"}
                        ]
                    }
                ],
            )
            is None
        )
        assert (
            _estimate_index_from_monthly(
                12.0,
                date(2026, 9, 1),
                date(2026, 9, 2),
                [
                    {
                        "consumptions": [
                            {"rangeType": "Day", "startDate": "2026-09-02", "value": -0.1}
                        ]
                    }
                ],
            )
            is None
        )

    def test_ignores_non_day_and_out_of_range_entries(self) -> None:
        result = _estimate_index_from_monthly(
            10.0,
            date(2026, 9, 10),
            date(2026, 9, 12),
            [
                {
                    "consumptions": [
                        {"rangeType": "Month", "startDate": "bad", "value": "bad"},
                        {"rangeType": "Day", "startDate": "2026-09-09", "value": 99},
                        {"rangeType": "Day", "startDate": "2026-09-11", "value": 0.2},
                    ]
                }
            ],
        )
        assert result == 10.2


class TestConsumptionExtractorsEdges:
    def test_has_nonzero_day_handles_bad_and_valid_values(self) -> None:
        assert not _has_nonzero_day({"consumptions": [{"rangeType": "Day", "value": "bad"}]})
        assert _has_nonzero_day({"consumptions": [{"rangeType": "Day", "value": "0.2"}]})

    def test_latest_daily_rejects_non_list_and_skips_bad_dates(self) -> None:
        assert _extract_latest_daily({"consumptions": "bad"}) == (None, None)
        assert _extract_latest_daily(
            {
                "consumptions": [
                    {"rangeType": "Day", "startDate": "bad", "value": 0.4},
                    {"rangeType": "Day", "startDate": "2026-09-10", "value": 0},
                ]
            }
        ) == (None, None)

    def test_week_from_monthly_handles_non_list_bad_dates_and_outside_week(self) -> None:
        assert _extract_week_total_from_monthly({"consumptions": "bad"}, date(2026, 9, 14)) is None
        result = _extract_week_total_from_monthly(
            {
                "consumptions": [
                    {"rangeType": "Day", "startDate": "bad", "value": 0.5},
                    {"rangeType": "Day", "startDate": "2026-09-13", "value": 1.0},
                    {"rangeType": "Day", "startDate": "2026-09-14", "value": 0.2},
                ]
            },
            date(2026, 9, 14),
        )
        assert result == 0.2

    def test_week_total_rejects_non_list(self) -> None:
        assert _extract_week_total_m3({"consumptions": "bad"}) is None

    def test_period_fallback_handles_negative_and_volume(self) -> None:
        assert _extract_period_m3({"value": -1}) is None
        assert _extract_period_m3({"volume": 1.2345}) == pytest.approx(1.234)
