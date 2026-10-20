"""SAURon integration entry point."""

from __future__ import annotations

import logging
import time
from datetime import date
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.const import Platform
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SauronApiClient, TokenCache
from .const import (
    CONF_LOGIN,
    CONF_PASSWORD,
    CONF_TOKEN_CACHE,
    DOMAIN,
    HASS_DATA_OPTIONS_SNAPSHOT,
    TOKEN_REFRESH_MARGIN_S,
)
from .coordinator import SauronCoordinator
from .historical import fetch_historical_preview

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]
_PREVIEW_SERVICE = "preview_historical"
_PREVIEW_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): str,
        vol.Required("start"): str,
        vol.Required("end"): str,
    }
)


async def _async_preview_historical(hass: HomeAssistant, call: Any) -> dict[str, Any]:
    """Read-only diagnostic; never update Recorder or the config entry."""
    coordinator = hass.data.get(DOMAIN, {}).get(call.data["entry_id"])
    if not isinstance(coordinator, SauronCoordinator):
        raise HomeAssistantError("Unknown SAURon config entry")
    try:
        start = date.fromisoformat(call.data["start"])
        end = date.fromisoformat(call.data["end"])
    except ValueError as err:
        raise HomeAssistantError("Dates must use YYYY-MM-DD") from err
    if start > end or (end - start).days > 35:
        raise HomeAssistantError("Historical preview requires an interval of at most 36 days")
    entry = coordinator.config_entry
    existing = entry.data.get("_dated_statistics_daily_ledger") or {}
    try:
        preview = await fetch_historical_preview(
            coordinator._client,
            entry.data["subscription_id"],
            start,
            end,
            existing,
        )
    except Exception as err:
        _LOGGER.warning("Historical SAUR preview failed: %s", err)
        raise HomeAssistantError("Historical SAUR preview failed; check logs") from err
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "returned_days": len(preview.values),
        "missing_days": list(preview.missing_days),
        "available_ranges": [list(item) for item in preview.available_ranges],
        "conflicts_with_ledger": {
            key: {"existing": old, "received": new}
            for key, (old, new) in preview.conflicts_with_ledger.items()
        },
        "complete": preview.complete,
        "read_only": True,
    }



async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SAURon from a config entry."""
    session = async_get_clientsession(hass)

    cached_token = _hydrate_token_from_entry(entry)

    async def _persist_token(cache: TokenCache) -> None:
        """Write the refreshed token cache back to entry.data.

        Note: this triggers ``_async_update_listener`` below, which uses an
        options snapshot to detect that the *options* did not change and
        therefore skips ``async_reload`` — see Plan A §3.5 (RC-1).
        """
        new_data = {**entry.data, CONF_TOKEN_CACHE: asdict(cache)}
        hass.config_entries.async_update_entry(entry, data=new_data)

    client = SauronApiClient(
        session=session,
        login=entry.data[CONF_LOGIN],
        password=entry.data[CONF_PASSWORD],
        initial_token=cached_token,
        on_token_refreshed=_persist_token,
    )

    coordinator = SauronCoordinator(hass, client, entry)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data[entry.entry_id] = coordinator
    # Snapshot the options at setup time. The update listener diffs against
    # this snapshot so that data-only updates (token cache writes) do NOT
    # trigger a coordinator reload.
    domain_data[f"{entry.entry_id}_{HASS_DATA_OPTIONS_SNAPSHOT}"] = dict(entry.options)

    if not hass.services.has_service(DOMAIN, _PREVIEW_SERVICE):
        async def _handle_preview(call: Any) -> dict[str, Any]:
            return await _async_preview_historical(hass, call)

        hass.services.async_register(
            DOMAIN,
            _PREVIEW_SERVICE,
            _handle_preview,
            schema=_PREVIEW_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        domain_data = hass.data.get(DOMAIN, {})
        domain_data.pop(entry.entry_id, None)
        domain_data.pop(f"{entry.entry_id}_{HASS_DATA_OPTIONS_SNAPSHOT}", None)
    return unloaded


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entry to current schema."""
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload only when ``entry.options`` changes — ignore data-only updates.

    Without this guard, ``async_update_entry(entry, data=...)`` from the
    token-refresh callback would trigger ``async_reload`` on every token
    refresh (~hourly), tearing down and rebuilding the coordinator.  See
    Plan A §3.5 (RC-1).
    """
    domain_data = hass.data.get(DOMAIN, {})
    snapshot_key = f"{entry.entry_id}_{HASS_DATA_OPTIONS_SNAPSHOT}"
    old_options = domain_data.get(snapshot_key, {})
    new_options = dict(entry.options)
    if new_options == old_options:
        # data-only update (token cache) — do not reload
        return
    domain_data[snapshot_key] = new_options
    await hass.config_entries.async_reload(entry.entry_id)


def _hydrate_token_from_entry(entry: ConfigEntry) -> TokenCache | None:
    """Rebuild a TokenCache from ``entry.data`` if present, valid, and not expired.

    Returns ``None`` (so the client will authenticate from scratch) if:
      - the entry has no cached token,
      - the cached blob is malformed (manual edit, schema drift),
      - the cached token is already within TOKEN_REFRESH_MARGIN_S of expiry.

    Silently swallows malformed data — no crash on startup.
    """
    raw: Any = entry.data.get(CONF_TOKEN_CACHE)
    if not isinstance(raw, dict):
        return None
    try:
        cache = TokenCache(
            access_token=str(raw["access_token"]),
            expires_at=float(raw["expires_at"]),
            client_id=str(raw["client_id"]),
            default_section_id=str(raw["default_section_id"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if time.time() >= cache.expires_at - TOKEN_REFRESH_MARGIN_S:
        return None
    return cache
