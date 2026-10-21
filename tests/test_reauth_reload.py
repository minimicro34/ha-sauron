"""Regression test for Home Assistant 2026.12 reauthentication reload handling."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.sauron.const import (
    CONF_CLIENT_ID,
    CONF_LOGIN,
    CONF_PASSWORD,
    CONF_SUBSCRIPTION_ID,
)


@pytest.mark.asyncio
async def test_reauth_updates_credentials_and_schedules_reload() -> None:
    """Exercise the real reauth method without importing the HA ConfigFlow stub."""
    source = (
        Path(__file__).resolve().parents[1]
        / "custom_components/sauron/config_flow.py"
    ).read_text(encoding="utf-8")
    module = ast.parse(source)
    flow_class = next(
        node for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "SauronConfigFlow"
    )
    method = next(
        node for node in flow_class.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "async_step_reauth_confirm"
    )
    # Compile the actual method body in isolation: the lightweight Home Assistant
    # stub models ConfigFlow as object and cannot accept domain= during import.
    isolated = ast.Module(body=[method], type_ignores=[])
    ast.fix_missing_locations(isolated)

    async def probe(session: object, login: str, password: str) -> tuple[str, str]:
        assert login == "updated@example.com"
        assert password == "new-password"
        return "CLIENT-2", "SUB-1"

    namespace = {
        "_probe_saur": probe,
        "async_get_clientsession": lambda hass: object(),
        "CONF_LOGIN": CONF_LOGIN,
        "CONF_PASSWORD": CONF_PASSWORD,
        "CONF_CLIENT_ID": CONF_CLIENT_ID,
        "CONF_SUBSCRIPTION_ID": CONF_SUBSCRIPTION_ID,
    }
    exec(compile(isolated, "config_flow.py", "exec"), namespace)
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={CONF_SUBSCRIPTION_ID: "SUB-1"},
    )
    result = {"type": "abort", "reason": "reauth_successful"}
    flow = MagicMock()
    flow._get_reauth_entry.return_value = entry
    flow.async_update_and_abort.return_value = result

    response = await namespace["async_step_reauth_confirm"](
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
