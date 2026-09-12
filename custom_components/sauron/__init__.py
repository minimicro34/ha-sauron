"""SAURon integration entry point."""

from __future__ import annotations

import logging
import time
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from homeassistant.const import Platform
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

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


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
