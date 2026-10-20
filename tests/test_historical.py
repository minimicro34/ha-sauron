"""Read-only historical backfill preparation tests."""

import sys
import types
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.sauron import (
    _async_preview_historical,
    _async_preview_historical_coverage,
)
from custom_components.sauron.const import DOMAIN
from custom_components.sauron.coordinator import SauronCoordinator
from custom_components.sauron.historical import (
    preview_monthly_payloads,
    summarize_historical_coverage,
)


def _payload(*items):
    return {
        "consumptions": [
            {"rangeType": "Day", "startDate": day, "value": value}
            for day, value in items
        ]
    }


def test_explicit_zero_is_not_missing():
    result = preview_monthly_payloads(
        [_payload(("2023-10-19", 0), ("2023-10-20", 0.1))],
        date(2023, 10, 19),
        date(2023, 10, 20),
    )
    assert result.complete
    assert result.values["2023-10-19"] == 0


def test_missing_dates_are_not_assumed_zero():
    result = preview_monthly_payloads(
        [_payload(("2023-10-20", 0.1))],
        date(2023, 10, 19),
        date(2023, 10, 21),
    )
    assert result.missing_days == ("2023-10-19", "2023-10-21")
    assert not result.complete


def test_existing_overlap_is_reported_without_mutation():
    existing = {"2026-05-29": 0.2}
    result = preview_monthly_payloads(
        [_payload(("2026-05-29", 0.3))],
        date(2026, 5, 29),
        date(2026, 5, 29),
        existing,
    )
    assert result.conflicts_with_ledger == {"2026-05-29": (0.2, 0.3)}
    assert existing == {"2026-05-29": 0.2}


def test_identical_duplicates_are_accepted():
    result = preview_monthly_payloads(
        [_payload(("2023-10-20", 0.1)), _payload(("2023-10-20", 0.1))],
        date(2023, 10, 20),
        date(2023, 10, 20),
    )
    assert result.complete


def test_conflicting_duplicates_are_rejected():
    with pytest.raises(ValueError, match="Conflicting historical"):
        preview_monthly_payloads(
            [_payload(("2023-10-20", 0.1)), _payload(("2023-10-20", 0.2))],
            date(2023, 10, 20),
            date(2023, 10, 20),
        )


@pytest.mark.parametrize("value", [-0.1, float("nan"), float("inf")])
def test_invalid_volume_is_rejected(value):
    with pytest.raises(ValueError, match="Invalid historical SAUR daily volume"):
        preview_monthly_payloads(
            [_payload(("2023-10-20", value))],
            date(2023, 10, 20),
            date(2023, 10, 20),
        )


def test_invalid_payload_is_rejected():
    with pytest.raises(ValueError, match="Invalid historical SAUR response"):
        preview_monthly_payloads(
            [{}], date(2023, 10, 20), date(2023, 10, 20)
        )


def test_available_ranges_keep_missing_days_as_gaps():
    result = preview_monthly_payloads(
        [_payload(
            ("2023-10-20", 0.1),
            ("2023-10-21", 0),
            ("2023-10-23", 0.2),
        )],
        date(2023, 10, 20),
        date(2023, 10, 24),
    )
    assert result.available_ranges == (
        ("2023-10-20", "2023-10-21"),
        ("2023-10-23", "2023-10-23"),
    )
    assert result.missing_days == ("2023-10-22", "2023-10-24")


def test_available_ranges_empty_when_no_readings():
    result = preview_monthly_payloads(
        [_payload()], date(2023, 10, 20), date(2023, 10, 21)
    )
    assert result.available_ranges == ()


def test_non_mapping_payload_is_rejected():
    with pytest.raises(ValueError, match="Invalid historical SAUR response"):
        preview_monthly_payloads(
            [None], date(2023, 10, 20), date(2023, 10, 20)
        )


@pytest.mark.asyncio
async def test_service_preview_read_only(monkeypatch, fake_entry):
    """Preview must report coverage and leave existing config data untouched."""
    errors = types.ModuleType("homeassistant.exceptions")
    class HomeAssistantError(Exception):
        pass
    errors.HomeAssistantError = HomeAssistantError
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", errors)

    fake_entry.data["subscription_id"] = "SUB001"
    client = AsyncMock()
    client.async_get_monthly.return_value = _payload(
        ("2023-10-20", 0.1), ("2023-10-21", 0)
    )
    coordinator = object.__new__(SauronCoordinator)
    coordinator.config_entry = fake_entry
    coordinator._client = client
    hass = SimpleNamespace(data={DOMAIN: {fake_entry.entry_id: coordinator}})
    before = dict(fake_entry.data)
    result = await _async_preview_historical(
        hass,
        SimpleNamespace(data={
            "entry_id": fake_entry.entry_id,
            "start": "2023-10-20",
            "end": "2023-10-22",
        }),
    )
    assert result["read_only"] is True
    assert result["returned_days"] == 2
    assert result["missing_days"] == ["2023-10-22"]
    assert result["available_ranges"] == [["2023-10-20", "2023-10-21"]]
    assert fake_entry.data == before
    client.async_get_monthly.assert_awaited_once_with("SUB001", 2023, 10)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("bad-date", "2023-10-21"),
        ("2023-10-22", "2023-10-20"),
        ("2023-10-01", "2023-11-07"),
    ],
)
async def test_service_rejects_invalid_dates(monkeypatch, fake_entry, start, end):

    errors = types.ModuleType("homeassistant.exceptions")
    class HomeAssistantError(Exception):
        pass
    errors.HomeAssistantError = HomeAssistantError
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", errors)
    coordinator = object.__new__(SauronCoordinator)
    coordinator.config_entry = fake_entry
    coordinator._client = AsyncMock()
    hass = SimpleNamespace(data={DOMAIN: {fake_entry.entry_id: coordinator}})
    with pytest.raises(HomeAssistantError):
        await _async_preview_historical(
            hass,
            SimpleNamespace(data={
                "entry_id": fake_entry.entry_id,
                "start": start,
                "end": end,
            }),
        )
    coordinator._client.async_get_monthly.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_rejects_unknown_entry(monkeypatch):
    import sys
    import types

    errors = types.ModuleType("homeassistant.exceptions")
    class HomeAssistantError(Exception):
        pass
    errors.HomeAssistantError = HomeAssistantError
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", errors)
    with pytest.raises(HomeAssistantError, match="Unknown"):
        await _async_preview_historical(
            SimpleNamespace(data={DOMAIN: {}}),
            SimpleNamespace(data={
                "entry_id": "unknown",
                "start": "2023-10-20",
                "end": "2023-10-21",
            }),
        )


def test_coverage_monthly_summary_and_ledger_overlap():
    ledger = {"2023-10-31": 0.1, "2023-11-01": 0.2}
    preview = preview_monthly_payloads(
        [_payload(("2023-10-31", 0.1), ("2023-11-01", 0.3))],
        date(2023, 10, 30),
        date(2023, 11, 2),
        ledger,
    )
    result = summarize_historical_coverage(preview, ledger)
    assert result["expected_days"] == 4
    assert result["returned_days"] == 2
    assert result["missing_days"] == ["2023-10-30", "2023-11-02"]
    assert result["ledger_overlap_days"] == 2
    assert result["ledger_conflicts"]["2023-11-01"] == {
        "existing": 0.2, "received": 0.3
    }
    assert result["months"] == [
        {
            "month": "2023-10", "expected_days": 2, "returned_days": 1,
            "missing_days": 1, "ledger_overlap_days": 1, "ledger_conflicts": 0,
        },
        {
            "month": "2023-11", "expected_days": 2, "returned_days": 1,
            "missing_days": 1, "ledger_overlap_days": 1, "ledger_conflicts": 1,
        },
    ]
    assert result["recorder_verified"] is False
    assert result["read_only"] is True
    assert ledger == {"2023-10-31": 0.1, "2023-11-01": 0.2}


@pytest.mark.asyncio
async def test_coverage_action_fetches_two_months_without_mutation(monkeypatch, fake_entry):
    errors = types.ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        pass

    errors.HomeAssistantError = HomeAssistantError
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", errors)
    client = AsyncMock()
    client.async_get_monthly.side_effect = [
        _payload(("2023-10-31", 0.1)),
        _payload(("2023-11-01", 0.2)),
    ]
    coordinator = object.__new__(SauronCoordinator)
    coordinator.config_entry = fake_entry
    coordinator._client = client
    hass = SimpleNamespace(data={DOMAIN: {fake_entry.entry_id: coordinator}})
    before = dict(fake_entry.data)
    result = await _async_preview_historical_coverage(
        hass,
        SimpleNamespace(data={
            "entry_id": fake_entry.entry_id,
            "start": "2023-10-31",
            "end": "2023-11-01",
        }),
    )
    assert result["complete"] is True
    assert result["returned_days"] == 2
    assert result["recorder_verified"] is False
    assert fake_entry.data == before
    assert client.async_get_monthly.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2023-10-01", "2026-10-01"),
        ("2024-01-02", "2024-01-01"),
        ("not-a-date", "2024-01-01"),
    ],
)
async def test_coverage_action_rejects_invalid_range(monkeypatch, fake_entry, start, end):
    errors = types.ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        pass

    errors.HomeAssistantError = HomeAssistantError
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", errors)
    coordinator = object.__new__(SauronCoordinator)
    coordinator.config_entry = fake_entry
    coordinator._client = AsyncMock()
    hass = SimpleNamespace(data={DOMAIN: {fake_entry.entry_id: coordinator}})
    with pytest.raises(HomeAssistantError):
        await _async_preview_historical_coverage(
            hass,
            SimpleNamespace(data={
                "entry_id": fake_entry.entry_id,
                "start": start,
                "end": end,
            }),
        )
    coordinator._client.async_get_monthly.assert_not_awaited()


def test_backfill_plan_preserves_existing_recorder_sums():
    from custom_components.sauron.historical import plan_historical_backfill
    from custom_components.sauron.statistics import build_ledger_statistics

    history = preview_monthly_payloads(
        [_payload(("2026-05-27", 0.4), ("2026-05-28", 0.6))],
        date(2026, 5, 27),
        date(2026, 5, 28),
    )
    ledger = {"2026-05-29": 0.2, "2026-05-30": 0.3}
    existing = build_ledger_statistics(ledger, "Europe/Paris")
    result = plan_historical_backfill(history, ledger, existing, "Europe/Paris")
    assert result["recorder_verified"] is True
    assert result["historical_days"] == 2
    assert result["existing_rows_unchanged"] is True
    assert [row["sum"] for row in result["historical_rows"]] == [-0.6, 0.0]
    assert existing == build_ledger_statistics(ledger, "Europe/Paris")


@pytest.mark.parametrize("tamper", ["missing", "sum", "state", "timestamp"])
def test_backfill_plan_rejects_recorder_discrepancies(tamper):
    from datetime import timedelta

    from custom_components.sauron.historical import plan_historical_backfill
    from custom_components.sauron.statistics import build_ledger_statistics

    history = preview_monthly_payloads(
        [_payload(("2026-05-28", 0.4))],
        date(2026, 5, 28),
        date(2026, 5, 28),
    )
    ledger = {"2026-05-29": 0.2}
    rows = build_ledger_statistics(ledger, "Europe/Paris")
    if tamper == "missing":
        rows = []
    elif tamper == "timestamp":
        rows[0]["start"] += timedelta(hours=1)
    else:
        rows[0][tamper] += 0.1
    with pytest.raises(ValueError, match="Recorder"):
        plan_historical_backfill(history, ledger, rows, "Europe/Paris")


def test_backfill_plan_rejects_missing_historical_boundary():
    from custom_components.sauron.historical import plan_historical_backfill
    from custom_components.sauron.statistics import build_ledger_statistics

    history = preview_monthly_payloads(
        [_payload(("2026-05-27", 0.4))],
        date(2026, 5, 27),
        date(2026, 5, 27),
    )
    ledger = {"2026-05-29": 0.2}
    with pytest.raises(ValueError, match="exactly one day"):
        plan_historical_backfill(
            history, ledger, build_ledger_statistics(ledger, "UTC"), "UTC"
        )


@pytest.mark.asyncio
async def test_import_rejects_missing_confirmation(monkeypatch, fake_entry):
    """An unconfirmed action must never fetch or enqueue Recorder writes."""
    from custom_components.sauron import _async_import_historical

    errors = types.ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        pass

    errors.HomeAssistantError = HomeAssistantError
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", errors)
    coordinator = object.__new__(SauronCoordinator)
    coordinator.config_entry = fake_entry
    coordinator._client = AsyncMock()
    hass = SimpleNamespace(data={DOMAIN: {fake_entry.entry_id: coordinator}})
    with pytest.raises(HomeAssistantError, match="confirm"):
        await _async_import_historical(
            hass,
            SimpleNamespace(data={
                "entry_id": fake_entry.entry_id,
                "start": "2023-10-16",
                "end": "2026-05-28",
                "confirm": False,
            }),
        )
    coordinator._client.async_get_monthly.assert_not_awaited()


def test_backfill_plan_rejects_existing_history_and_ledger_gaps():
    from custom_components.sauron.historical import plan_historical_backfill
    from custom_components.sauron.statistics import build_ledger_statistics

    history = preview_monthly_payloads(
        [_payload(("2026-05-28", 0.4))],
        date(2026, 5, 28),
        date(2026, 5, 28),
    )
    ledger = {"2026-05-29": 0.2, "2026-05-31": 0.3}
    with pytest.raises(ValueError, match="missing days"):
        plan_historical_backfill(
            history, ledger, build_ledger_statistics(ledger, "UTC"), "UTC"
        )


def test_backfill_plan_rejects_incomplete_history():
    from custom_components.sauron.historical import plan_historical_backfill
    from custom_components.sauron.statistics import build_ledger_statistics

    history = preview_monthly_payloads(
        [_payload(("2026-05-27", 0.4))],
        date(2026, 5, 27),
        date(2026, 5, 28),
    )
    ledger = {"2026-05-29": 0.2}
    with pytest.raises(ValueError, match="Incomplete historical"):
        plan_historical_backfill(
            history, ledger, build_ledger_statistics(ledger, "UTC"), "UTC"
        )
