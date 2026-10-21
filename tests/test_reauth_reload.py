"""Regression tests for Home Assistant 2026.12 reauthentication reload handling."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.sauron import config_flow
from custom_components.sauron.const import (
    CONF_CLIENT_ID,
    CONF_LOGIN,
    CONF_PASSWORD,
    CONF_SUBSCRIPTION_ID,
)


@pytest.mark.asyncio
async def test_reauth_updates_credentials_and_schedules_reload(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful reauth must not call async_update_reload_and_abort."""
    async def probe(session: object, login: str, password: str) -> tuple[str, str]:
        assert login == "updated@example.com"
        assert password == "new-password"
        return "CLIENT-2", "SUB-1"

    monkeypatch.setattr(config_flow, "_probe_saur", probe)
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={CONF_SUBSCRIPTION_ID: "SUB-1"},
    )
    result = {"type": "abort", "reason": "reauth_successful"}
    flow = MagicMock()
    flow._get_reauth_entry.return_value = entry
    flow.async_update_and_abort.return_value = result
    flow.hass.config_entries.async_schedule_reload = MagicMock()
    monkeypatch.setattr(config_flow, "async_get_clientsession", lambda hass: object())

    response = await config_flow.SauronConfigFlow.async_step_reauth_confirm(
        flow, {CONF_LOGIN: "updated@example.com", CONF_PASSWORD: "new-password"}
    )

    assert response == result
    flow.async_update_and_abort.assert_called_once_with(
        entry,
        data_updates={
            CONF_LOGIN: "updated@example.com",
            CONF_PASSWORD: "new-password",
            CONF_CLIENT_ID: "CLIENT-2",
        },
    )
    flow.hass.config_entries.async_schedule_reload.assert_called_once_with("entry-1")
    flow.async_update_reload_and_abort.assert_not_called()
