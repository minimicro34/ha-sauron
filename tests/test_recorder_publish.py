"""Recorder publication safety tests with isolated Home Assistant recorder stubs."""

import sys
from datetime import date
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.sauron.coordinator import SauronCoordinator


def _coordinator(enabled=True, anchor=None, running=True, payload=None, ledger=None):
    entry_data = {"subscription_id": "SUB001"}
    if anchor is not None:
        entry_data["_dated_statistics_anchor"] = anchor
    if ledger is not None:
        entry_data["_dated_statistics_daily_ledger"] = ledger
    entry = SimpleNamespace(
        entry_id="TEST_ENTRY",
        data=entry_data,
        options={"enable_dated_statistics": enabled},
    )
    hass = SimpleNamespace(
        is_running=running,
        config=SimpleNamespace(time_zone="Europe/Paris"),
        config_entries=SimpleNamespace(async_update_entry=MagicMock()),
    )
    coordinator = object.__new__(SauronCoordinator)
    coordinator.config_entry = entry
    coordinator.hass = hass
    coordinator._monthly_index_payloads = payload
    return coordinator, entry, hass


def _recorder_modules():
    models = ModuleType("homeassistant.components.recorder.models.statistics")
    models.StatisticMeanType = SimpleNamespace(NONE=0)
    statistics = ModuleType("homeassistant.components.recorder.statistics")
    statistics.async_add_external_statistics = MagicMock()
    return {
        "homeassistant.components.recorder.models.statistics": models,
        "homeassistant.components.recorder.statistics": statistics,
    }


def test_recorder_disabled_does_not_write():
    coordinator, _, hass = _coordinator(enabled=False, payload=[{"consumptions": []}])
    with patch.dict(sys.modules, _recorder_modules()):
        coordinator._publish_dated_statistics(date(2026, 10, 10), date(2026, 10, 11))
    hass.config_entries.async_update_entry.assert_not_called()


def test_recorder_import_persists_anchor_after_validation():
    payload = [{"consumptions": [
        {"rangeType": "Day", "startDate": "2026-10-11", "value": 0.9},
    ]}]
    coordinator, entry, hass = _coordinator(payload=payload)
    modules = _recorder_modules()
    with patch.dict(sys.modules, modules):
        coordinator._publish_dated_statistics(date(2026, 10, 10), date(2026, 10, 11))
    imported = modules["homeassistant.components.recorder.statistics"]
    imported.async_add_external_statistics.assert_called_once()
    args = imported.async_add_external_statistics.call_args.args
    assert args[1]["statistic_id"] == "sauron:daily_water_test_entry"
    assert args[2][0]["sum"] == 0.9
    hass.config_entries.async_update_entry.assert_called_once()
    assert entry.data.get("_dated_statistics_daily_ledger") is None
    saved_data = hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert saved_data["_dated_statistics_daily_ledger"] == {"2026-10-11": 0.9}


def test_recorder_legacy_anchor_without_ledger_does_not_write():
    coordinator, _, hass = _coordinator(
        anchor="2026-10-09",
        payload=[{"consumptions": [{"rangeType": "Day", "startDate": "2026-10-11", "value": 0.9}]}],
    )
    modules = _recorder_modules()
    with patch.dict(sys.modules, modules):
        coordinator._publish_dated_statistics(date(2026, 10, 10), date(2026, 10, 11))
    recorder = modules["homeassistant.components.recorder.statistics"]
    recorder.async_add_external_statistics.assert_not_called()
    hass.config_entries.async_update_entry.assert_not_called()


def test_recorder_incomplete_history_does_not_write_or_persist():
    coordinator, _, hass = _coordinator(
        payload=[{"consumptions": [{"rangeType": "Day", "startDate": "2026-10-12", "value": 0.9}]}],
    )
    modules = _recorder_modules()
    with patch.dict(sys.modules, modules):
        coordinator._publish_dated_statistics(date(2026, 10, 10), date(2026, 10, 12))
    modules["homeassistant.components.recorder.statistics"].async_add_external_statistics.assert_not_called()
    hass.config_entries.async_update_entry.assert_not_called()


def test_recorder_continues_after_physical_reading() -> None:
    coordinator, _, hass = _coordinator(
        ledger={"2026-10-11": 0.9, "2026-10-12": 0.2},
        payload=[{"consumptions": [
            {"rangeType": "Day", "startDate": "2026-10-13", "value": 0.3},
        ]}],
    )
    modules = _recorder_modules()
    with patch.dict(sys.modules, modules):
        coordinator._publish_dated_statistics(date(2026, 10, 12), date(2026, 10, 13))
    imported = modules["homeassistant.components.recorder.statistics"]
    imported.async_add_external_statistics.assert_called_once()
    rows = imported.async_add_external_statistics.call_args.args[2]
    assert [row["sum"] for row in rows] == [0.9, 1.1, 1.4]
    saved_data = hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert saved_data["_dated_statistics_daily_ledger"]["2026-10-13"] == 0.3


def test_recorder_rejects_gap_between_readings() -> None:
    coordinator, _, hass = _coordinator(
        ledger={"2026-10-11": 0.9},
        payload=[{"consumptions": [
            {"rangeType": "Day", "startDate": "2026-10-15", "value": 0.3},
        ]}],
    )
    modules = _recorder_modules()
    with patch.dict(sys.modules, modules):
        coordinator._publish_dated_statistics(date(2026, 10, 14), date(2026, 10, 15))
    modules["homeassistant.components.recorder.statistics"].async_add_external_statistics.assert_not_called()
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_delayed_days_bridge_new_physical_reading() -> None:
    coordinator, _, hass = _coordinator(
        ledger={"2026-09-29": 0.4, "2026-09-30": 0.5},
    )
    coordinator._client = SimpleNamespace(
        async_get_monthly=AsyncMock(
            return_value={
                "consumptions": [
                    {"rangeType": "Day", "startDate": "2026-10-01", "value": 0.2},
                    {"rangeType": "Day", "startDate": "2026-10-02", "value": 0.3},
                ]
            }
        )
    )
    await coordinator._async_refresh_recorder_history(
        "SUB001", date(2026, 10, 2), date(2026, 10, 3)
    )
    assert coordinator._client.async_get_monthly.await_count == 2
    modules = _recorder_modules()
    with patch.dict(sys.modules, modules):
        coordinator._publish_dated_statistics(date(2026, 10, 2), date(2026, 10, 3))
    imported = modules["homeassistant.components.recorder.statistics"]
    rows = imported.async_add_external_statistics.call_args.args[2]
    assert [row["sum"] for row in rows] == [0.4, 0.9, 1.1, 1.4]
    saved_data = hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert saved_data["_dated_statistics_daily_ledger"]["2026-10-01"] == 0.2


@pytest.mark.asyncio
async def test_failed_backfill_preserves_existing_ledger() -> None:
    coordinator, entry, hass = _coordinator(
        ledger={"2026-09-30": 0.5},
    )
    coordinator._client = SimpleNamespace(
        async_get_monthly=AsyncMock(side_effect=RuntimeError("SAUR unavailable"))
    )
    await coordinator._async_refresh_recorder_history(
        "SUB001", date(2026, 10, 2), date(2026, 10, 3)
    )
    assert coordinator._monthly_index_payloads is None
    modules = _recorder_modules()
    with patch.dict(sys.modules, modules):
        coordinator._publish_dated_statistics(date(2026, 10, 2), date(2026, 10, 3))
    modules["homeassistant.components.recorder.statistics"].async_add_external_statistics.assert_not_called()
    hass.config_entries.async_update_entry.assert_not_called()
    assert entry.data["_dated_statistics_daily_ledger"] == {"2026-09-30": 0.5}
