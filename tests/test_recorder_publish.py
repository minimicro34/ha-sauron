"""Recorder publication safety tests with isolated Home Assistant recorder stubs."""

from datetime import date
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch
import sys

from custom_components.sauron.coordinator import SauronCoordinator


def _coordinator(enabled=True, anchor=None, running=True, payload=None):
    entry_data = {"subscription_id": "SUB001"}
    if anchor is not None:
        entry_data["_dated_statistics_anchor"] = anchor
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
    assert entry.data.get("_dated_statistics_anchor") is None


def test_recorder_changed_anchor_does_not_write():
    coordinator, _, hass = _coordinator(
        anchor="2026-10-09",
        payload=[{"consumptions": [{"rangeType": "Day", "startDate": "2026-10-11", "value": 0.9}]}],
    )
    modules = _recorder_modules()
    with patch.dict(sys.modules, modules):
        coordinator._publish_dated_statistics(date(2026, 10, 10), date(2026, 10, 11))
    modules["homeassistant.components.recorder.statistics"].async_add_external_statistics.assert_not_called()
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
