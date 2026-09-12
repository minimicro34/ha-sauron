"""Pytest fixtures for the SAURon test suite."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from custom_components.sauron.api.models import MeterInfo, MeterReading, SauronData


@pytest.fixture
def mock_meter_info() -> MeterInfo:
    return MeterInfo(
        subscription_id="100030690002033754",
        address="1 rue de la Paix, 75001 Paris",
        meter_serial="METER123456",
        installation_date=date(2020, 1, 1),
    )


@pytest.fixture
def mock_reading(mock_meter_info: MeterInfo) -> MeterReading:
    return MeterReading(
        subscription_id=mock_meter_info.subscription_id,
        value_m3=1234.567,
        reading_date=date(2026, 6, 15),
        fetched_at=datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC),
    )


@pytest.fixture
def mock_saur_data(mock_meter_info: MeterInfo, mock_reading: MeterReading) -> SauronData:
    return SauronData(
        meter_info=mock_meter_info,
        latest_reading=mock_reading,
        daily_liters=85.3,
        weekly_m3=0.612,
        monthly_m3=2.456,
        yearly_m3=18.234,
    )


@pytest.fixture
def mock_api_client() -> AsyncMock:
    client = AsyncMock()
    client.async_authenticate = AsyncMock()
    client.async_get_meter_last_index = AsyncMock(
        return_value={
            "indexValue": 1234.567,
            "readingDate": "2026-06-15T00:00:00",
        }
    )
    client.async_get_weekly = AsyncMock(
        return_value={
            "consumptions": [
                {
                    "startDate": "2026-06-09T00:00:00",
                    "endDate": "2026-06-10T00:00:00",
                    "value": 0.085,
                    "rangeType": "Day",
                },
                {
                    "startDate": "2026-06-10T00:00:00",
                    "endDate": "2026-06-11T00:00:00",
                    "value": 0.092,
                    "rangeType": "Day",
                },
            ],
            "isRemoteReading": True,
        }
    )
    client.async_get_monthly = AsyncMock(return_value={"consumptions": []})
    client.async_get_yearly = AsyncMock(return_value={"consumptions": []})
    return client


# ── Lightweight Home Assistant fakes (Plan A persistence tests) ──────────────
#
# These fakes intentionally avoid the pytest-homeassistant-custom-component
# dependency.  They emulate just enough of ConfigEntry / HomeAssistant for
# the integration's __init__ module to exercise hydration, persistence, and
# the reload-guard listener.


class FakeConfigEntry:
    """Minimal stand-in for homeassistant.config_entries.ConfigEntry."""

    def __init__(
        self,
        *,
        entry_id: str = "test_entry_1",
        data: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        self.entry_id = entry_id
        self.data: dict[str, Any] = dict(data or {})
        self.options: dict[str, Any] = dict(options or {})
        self._unload_callbacks: list[Any] = []
        self._update_listeners: list[Any] = []

    def async_on_unload(self, callback: Any) -> None:
        self._unload_callbacks.append(callback)

    def add_update_listener(self, listener: Any) -> Any:
        self._update_listeners.append(listener)

        def _remove() -> None:
            self._update_listeners.remove(listener)

        return _remove


class FakeConfigEntries:
    """Minimal stand-in for hass.config_entries — captures reload + update calls."""

    def __init__(self, hass: FakeHomeAssistant) -> None:
        self._hass = hass
        self.reload_calls: list[str] = []

    async def async_reload(self, entry_id: str) -> bool:
        self.reload_calls.append(entry_id)
        return True

    def async_update_entry(
        self,
        entry: FakeConfigEntry,
        *,
        data: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> bool:
        if data is not None:
            entry.data = dict(data)
        if options is not None:
            entry.options = dict(options)
        for listener in list(entry._update_listeners):
            self._hass._pending_listener_calls.append(listener(self._hass, entry))
        return True


class FakeHomeAssistant:
    """Minimal stand-in for HomeAssistant exposing .data and .config_entries."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.config_entries: FakeConfigEntries = FakeConfigEntries(self)
        self._pending_listener_calls: list[Any] = []

    async def _drain_update_listeners(self) -> None:
        """Await any update-listener coroutines queued by async_update_entry."""
        pending = self._pending_listener_calls
        self._pending_listener_calls = []
        for coro in pending:
            await coro


@pytest.fixture
def fake_hass() -> FakeHomeAssistant:
    return FakeHomeAssistant()


@pytest.fixture
def fake_entry() -> FakeConfigEntry:
    return FakeConfigEntry(
        entry_id="entry_1",
        data={
            "login": "user@example.com",
            "password": "secret",
            "subscription_id": "SUB001",
            "client_id": "CLI001",
        },
        options={},
    )
