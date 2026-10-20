"""SAURon integration entry point."""

from __future__ import annotations

import logging
import time
from dataclasses import asdict
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

import voluptuous as vol
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
from .historical import (
    fetch_historical_preview,
    plan_historical_backfill,
    summarize_historical_coverage,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]
_PREVIEW_SERVICE = "preview_historical"
_COVERAGE_SERVICE = "preview_historical_coverage"
_IMPORT_SERVICE = "import_historical"
_PREVIEW_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): str,
        vol.Required("start"): str,
        vol.Required("end"): str,
    }
)


async def _async_preview_historical(hass: HomeAssistant, call: Any) -> dict[str, Any]:
    """Read-only diagnostic; never update Recorder or the config entry."""
    from homeassistant.exceptions import HomeAssistantError

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




async def _async_preview_historical_coverage(hass: HomeAssistant, call: Any) -> dict[str, Any]:
    """Inspect up to 36 historical months without modifying any HA data."""
    from homeassistant.exceptions import HomeAssistantError

    coordinator = hass.data.get(DOMAIN, {}).get(call.data["entry_id"])
    if not isinstance(coordinator, SauronCoordinator):
        raise HomeAssistantError("Unknown SAURon config entry")
    try:
        start = date.fromisoformat(call.data["start"])
        end = date.fromisoformat(call.data["end"])
    except ValueError as err:
        raise HomeAssistantError("Dates must use YYYY-MM-DD") from err
    months = (end.year - start.year) * 12 + end.month - start.month + 1
    if start > end or months > 36:
        raise HomeAssistantError("Historical coverage requires at most 36 calendar months")
    entry = coordinator.config_entry
    existing = entry.data.get("_dated_statistics_daily_ledger") or {}
    if not isinstance(existing, dict):
        raise HomeAssistantError("Invalid persisted daily ledger")
    try:
        preview = await fetch_historical_preview(
            coordinator._client,
            entry.data["subscription_id"],
            start,
            end,
            existing,
        )
    except Exception as err:
        _LOGGER.warning("Historical SAUR coverage failed: %s", err)
        raise HomeAssistantError("Historical SAUR coverage failed; check logs") from err
    return summarize_historical_coverage(preview, existing)




async def _async_import_historical(hass: HomeAssistant, call: Any) -> dict[str, Any]:
    """Queue a manual backfill only after verifying every existing Recorder row."""
    from homeassistant.components.recorder.models.statistics import StatisticMeanType
    from homeassistant.components.recorder.statistics import (
        async_add_external_statistics,
        statistics_during_period,
    )
    from homeassistant.exceptions import HomeAssistantError

    coordinator = hass.data.get(DOMAIN, {}).get(call.data["entry_id"])
    if not isinstance(coordinator, SauronCoordinator):
        raise HomeAssistantError("Unknown SAURon config entry")
    if call.data.get("confirm") is not True:
        raise HomeAssistantError("Explicit confirm: true is required")
    entry = coordinator.config_entry
    ledger = entry.data.get("_dated_statistics_daily_ledger")
    if not isinstance(ledger, dict) or not ledger:
        raise HomeAssistantError("Missing persisted SAURon daily ledger")
    try:
        start = date.fromisoformat(call.data["start"])
        end = date.fromisoformat(call.data["end"])
        months = (end.year - start.year) * 12 + end.month - start.month + 1
        if start > end or months > 36:
            raise ValueError("Historical import requires at most 36 calendar months")
        if end + timedelta(days=1) != date.fromisoformat(min(ledger)):
            raise ValueError("Historical period must join the existing ledger exactly")
    except ValueError as err:
        raise HomeAssistantError(str(err)) from err

    statistic_id = f"{DOMAIN}:daily_water_{entry.entry_id.lower()}"
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(hass.config.time_zone)
    first_existing = date.fromisoformat(min(ledger))
    last_existing = date.fromisoformat(max(ledger))
    first_utc = datetime.combine(start, time.min, tzinfo=zone).astimezone(UTC)
    end_utc = datetime.combine(
        last_existing + timedelta(days=1), time.min, tzinfo=zone
    ).astimezone(UTC)

    # Recorder's database access must run in an executor, never in the event loop.
    def _read_recorder() -> list[dict[str, Any]]:
        data = statistics_during_period(
            hass, first_utc, end_utc, {statistic_id}, "hour", None,
            {"state", "sum"},
        )
        return list(data.get(statistic_id, []))

    try:
        recorded = await hass.async_add_executor_job(_read_recorder)
        if not recorded:
            raise ValueError("Recorder has no existing long-term statistics")
        existing_start_utc = datetime.combine(
            first_existing, time.min, tzinfo=zone
        ).astimezone(UTC)
        if any(
            datetime.fromtimestamp(row["start"], tz=UTC) < existing_start_utc
            for row in recorded
        ):
            raise ValueError("Recorder already contains historical statistics")
        normalized = [
            {
                "start": datetime.fromtimestamp(row["start"], tz=UTC),
                "state": row.get("state"),
                "sum": row.get("sum"),
            }
            for row in recorded
        ]
        preview = await fetch_historical_preview(
            coordinator._client,
            entry.data["subscription_id"],
            start,
            end,
            ledger,
        )
        plan = plan_historical_backfill(
            preview, ledger, normalized, hass.config.time_zone
        )
        # Guard against a changed ledger while the 32 monthly calls were running.
        if entry.data.get("_dated_statistics_daily_ledger") != ledger:
            raise ValueError("SAURon daily ledger changed during preflight")
        metadata = {
            "statistic_id": statistic_id,
            "source": DOMAIN,
            "name": f"SAURon dated water ({entry.data['subscription_id']})",
            "unit_of_measurement": "m³",
            "unit_class": "volume",
            "has_sum": True,
            "mean_type": StatisticMeanType.NONE,
        }
        async_add_external_statistics(hass, metadata, plan["historical_rows"])
    except (KeyError, TypeError, ValueError, RuntimeError) as err:
        _LOGGER.warning("Historical SAUR import blocked: %s", err)
        raise HomeAssistantError(f"Historical SAUR import blocked: {err}") from err

    return {
        "status": "queued",
        "historical_days": plan["historical_days"],
        "historical_total_m3": plan["historical_total_m3"],
        "existing_days_verified": plan["existing_days"],
        "existing_rows_unchanged": True,
        "recorder_write_completed": False,
        "note": "Recorder import is queued asynchronously; verify after Recorder processes it.",
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

    if hasattr(hass, "services") and not hass.services.has_service(DOMAIN, _PREVIEW_SERVICE):
        from homeassistant.core import SupportsResponse
        async def _handle_preview(call: Any) -> dict[str, Any]:
            return await _async_preview_historical(hass, call)

        hass.services.async_register(
            DOMAIN,
            _PREVIEW_SERVICE,
            _handle_preview,
            schema=_PREVIEW_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    if hasattr(hass, "services") and not hass.services.has_service(DOMAIN, _COVERAGE_SERVICE):
        from homeassistant.core import SupportsResponse

        async def _handle_coverage(call: Any) -> dict[str, Any]:
            return await _async_preview_historical_coverage(hass, call)

        hass.services.async_register(
            DOMAIN,
            _COVERAGE_SERVICE,
            _handle_coverage,
            schema=_PREVIEW_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )


    if hasattr(hass, "services") and not hass.services.has_service(DOMAIN, _IMPORT_SERVICE):
        from homeassistant.core import SupportsResponse

        async def _handle_import(call: Any) -> dict[str, Any]:
            return await _async_import_historical(hass, call)

        hass.services.async_register(
            DOMAIN,
            _IMPORT_SERVICE,
            _handle_import,
            schema=_PREVIEW_SCHEMA.extend({vol.Required("confirm"): bool}),
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
