"""DataUpdateCoordinator for the SAURon integration."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SauronApiClient, SauronAuthError, SauronData
from .api.exceptions import SauronNoDataError, SauronTransientError
from .api.models import MeterInfo, MeterReading
from .const import (
    CONF_SUBSCRIPTION_ID,
    DEFAULT_SCAN_INTERVAL_H,
    DEFAULT_STALE_DATA_THRESHOLD_H,
    DOMAIN,
    ISSUE_STALE_DATA,
    OPT_SCAN_INTERVAL_H,
    OPT_STALE_DATA_THRESHOLD_H,
)

_LOGGER = logging.getLogger(__name__)
_ESTIMATED_INDEX_RETRY_MINUTES = (2, 5, 10)


class SauronCoordinator(DataUpdateCoordinator[SauronData]):
    """Fetch SAUR water consumption data on a configurable schedule."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, client: SauronApiClient, entry: ConfigEntry) -> None:
        scan_interval_h = entry.options.get(OPT_SCAN_INTERVAL_H, DEFAULT_SCAN_INTERVAL_H)
        normal_interval = timedelta(hours=scan_interval_h)
        super().__init__(
            hass,
            _LOGGER,
            name=f"SAURon ({entry.data[CONF_SUBSCRIPTION_ID]})",
            update_interval=normal_interval,
            config_entry=entry,
            always_update=False,
        )
        self._client = client
        self._normal_update_interval = normal_interval
        self._estimated_index_failures = 0
        self._stale_threshold_h = entry.options.get(
            OPT_STALE_DATA_THRESHOLD_H, DEFAULT_STALE_DATA_THRESHOLD_H
        )
        subscription_id: str = entry.data[CONF_SUBSCRIPTION_ID]
        self._meter_info = MeterInfo(
            subscription_id=subscription_id,
            address="",
            meter_serial="",
            installation_date=None,
        )

    async def async_setup(self) -> None:
        """Fetch static meter metadata once at integration setup."""
        subscription_id: str = self.config_entry.data[CONF_SUBSCRIPTION_ID]
        try:
            raw_points = await self._client.async_get_delivery_points(subscription_id)
            self._meter_info = _parse_delivery_points(subscription_id, raw_points)
        except Exception as err:
            _LOGGER.warning("Could not fetch delivery points for %s: %s", subscription_id, err)

    async def _async_update_data(self) -> SauronData:
        """Fetch latest data from the SAUR API."""
        subscription_id: str = self.config_entry.data[CONF_SUBSCRIPTION_ID]
        now = datetime.now(UTC)
        yesterday = now.date() - timedelta(days=1)

        try:
            raw_index = await self._client.async_get_meter_last_index(subscription_id)
        except SauronAuthError as err:
            raise ConfigEntryAuthFailed from err
        except SauronTransientError as err:
            raise UpdateFailed(f"SAUR API transient error: {err}") from err
        except SauronNoDataError as err:
            _LOGGER.warning("Unexpected SAUR payload for %s: %s", subscription_id, err)
            raise UpdateFailed(f"SAUR payload error: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"SAUR API error: {err}") from err

        data = _parse_last_index(subscription_id, raw_index, now, self._meter_info)
        estimated_index_m3 = await self._async_estimated_index(
            subscription_id, data.latest_reading, yesterday
        )

        raw_monthly: dict[str, Any] = {}
        try:
            raw_monthly = await self._client.async_get_monthly(subscription_id, now.year, now.month)
            if not _has_nonzero_day(raw_monthly):
                prev = now.replace(day=1) - timedelta(days=1)
                raw_monthly = await self._client.async_get_monthly(
                    subscription_id, prev.year, prev.month
                )
        except SauronAuthError as err:
            raise ConfigEntryAuthFailed from err
        except SauronTransientError as err:
            _LOGGER.warning(
                "SAUR monthly transient error for %s: %s — skipping enrichment",
                subscription_id,
                err,
            )
        except Exception as err:
            _LOGGER.warning("Could not fetch monthly data for %s: %s", subscription_id, err)

        daily_liters, daily_date = _extract_latest_daily(raw_monthly)
        weekly_m3 = _extract_week_total_from_monthly(raw_monthly, yesterday)
        monthly_m3 = _extract_period_m3(raw_monthly)

        yearly_m3: float | None = None
        try:
            raw_yearly = await self._client.async_get_yearly(subscription_id, now.year)
            yearly_m3 = _extract_period_m3(raw_yearly)
        except SauronAuthError as err:
            raise ConfigEntryAuthFailed from err
        except SauronTransientError as err:
            _LOGGER.debug(
                "SAUR yearly transient error for %s: %s — skipping yearly enrichment",
                subscription_id,
                err,
            )
        except Exception as err:
            _LOGGER.debug("Could not fetch yearly data for %s: %s", subscription_id, err)

        enriched = SauronData(
            meter_info=data.meter_info,
            latest_reading=data.latest_reading,
            estimated_index_m3=estimated_index_m3,
            daily_liters=daily_liters,
            daily_date=daily_date,
            weekly_m3=weekly_m3,
            monthly_m3=monthly_m3,
            yearly_m3=yearly_m3,
        )

        reading_age_h = (now.date() - enriched.latest_reading.reading_date).days * 24 + now.hour
        issue_id = f"{ISSUE_STALE_DATA}_{self.config_entry.entry_id}"
        if reading_age_h > self._stale_threshold_h:
            async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=IssueSeverity.WARNING,
                translation_key=ISSUE_STALE_DATA,
                translation_placeholders={
                    "subscription_id": subscription_id,
                    "age_h": f"{reading_age_h:.0f}",
                },
            )
        else:
            async_delete_issue(self.hass, DOMAIN, issue_id)
        return enriched

    async def _async_estimated_index(
        self, subscription_id: str, reading: MeterReading, through_date: date
    ) -> float | None:
        """Estimate the cumulative index and back off briefly on transient failures."""
        if through_date <= reading.reading_date:
            self._estimated_index_recovered(subscription_id)
            return round(reading.value_m3, 3)

        monthly_payloads: list[dict[str, Any]] = []
        for year, month in _iter_months(reading.reading_date, through_date):
            try:
                payload = await self._client.async_get_monthly(subscription_id, year, month)
            except SauronAuthError as err:
                raise ConfigEntryAuthFailed from err
            except SauronTransientError as err:
                return self._estimated_index_transient_failure(subscription_id, year, month, err)
            except Exception as err:
                _LOGGER.warning(
                    "Could not build estimated water index for %s: monthly data "
                    "%04d-%02d failed: %s",
                    subscription_id,
                    year,
                    month,
                    err,
                )
                return self._previous_estimated_index()
            monthly_payloads.append(payload)

        estimated = _estimate_index_from_monthly(
            reading.value_m3, reading.reading_date, through_date, monthly_payloads
        )
        if estimated is None:
            _LOGGER.warning(
                "Could not build estimated water index for %s: incomplete monthly payload",
                subscription_id,
            )
            return self._previous_estimated_index()

        self._estimated_index_recovered(subscription_id)
        return estimated

    def _previous_estimated_index(self) -> float | None:
        """Return the last valid estimate, when one is available."""
        if self.data is None:
            return None
        return self.data.estimated_index_m3

    def _estimated_index_transient_failure(
        self,
        subscription_id: str,
        year: int,
        month: int,
        err: SauronTransientError,
    ) -> float | None:
        """Keep the last estimate and shorten the next coordinator interval."""
        self._estimated_index_failures += 1
        retry_index = min(
            self._estimated_index_failures - 1,
            len(_ESTIMATED_INDEX_RETRY_MINUTES) - 1,
        )
        retry_minutes = _ESTIMATED_INDEX_RETRY_MINUTES[retry_index]
        self.update_interval = timedelta(minutes=retry_minutes)
        previous = self._previous_estimated_index()
        if self._estimated_index_failures == 1:
            _LOGGER.warning(
                "SAUR monthly data %04d-%02d temporarily unavailable for %s: %s. "
                "Keeping previous estimated index; retrying in %d minutes",
                year,
                month,
                subscription_id,
                err,
                retry_minutes,
            )
        else:
            _LOGGER.debug(
                "SAUR monthly data %04d-%02d still unavailable for %s (attempt %d): %s. "
                "Retrying in %d minutes",
                year,
                month,
                subscription_id,
                self._estimated_index_failures,
                err,
                retry_minutes,
            )
        return previous

    def _estimated_index_recovered(self, subscription_id: str) -> None:
        """Restore the normal polling interval after a transient failure."""
        if self._estimated_index_failures:
            _LOGGER.info(
                "SAUR monthly data recovered for %s after %d failed attempt%s; "
                "estimated water index is updating normally again",
                subscription_id,
                self._estimated_index_failures,
                "" if self._estimated_index_failures == 1 else "s",
            )
            self._estimated_index_failures = 0
        self.update_interval = self._normal_update_interval


def _parse_last_index(
    subscription_id: str,
    raw: dict[str, Any],
    fetched_at: datetime,
    meter_info: MeterInfo | None = None,
) -> SauronData:
    """Parse GET /meter_indexes/last response."""
    if not isinstance(raw, dict):
        raise SauronNoDataError(f"Expected dict from meter_indexes/last, got {type(raw)}")
    index_value = raw.get("indexValue")
    if index_value is None:
        raise SauronNoDataError("indexValue missing from meter_indexes/last response")
    raw_date = raw.get("readingDate", "")
    try:
        reading_date = date.fromisoformat(str(raw_date)[:10])
    except (ValueError, TypeError):
        reading_date = fetched_at.date()
    if meter_info is None:
        meter_info = MeterInfo(subscription_id, "", "", None)
    reading = MeterReading(subscription_id, float(index_value), reading_date, fetched_at)
    return SauronData(meter_info=meter_info, latest_reading=reading)


def _parse_delivery_points(subscription_id: str, raw: dict[str, Any]) -> MeterInfo:
    """Parse delivery-point meter metadata."""
    meter = raw.get("meter") or {}
    addr = raw.get("geographicAddress") or {}
    raw_install = meter.get("installationDate", "")
    try:
        installation_date = date.fromisoformat(str(raw_install)[:10])
    except (ValueError, TypeError):
        installation_date = None
    raw_brand = str(meter.get("meterBrandCode") or "")
    manufacturer = raw_brand.split("(")[0].strip() if raw_brand else ""
    raw_model = str(meter.get("meterModelCode") or "")
    model = raw_model.lstrip("t").strip() if raw_model else ""
    return MeterInfo(
        subscription_id=subscription_id,
        address=str(addr.get("city") or ""),
        meter_serial=str(meter.get("serialNumber") or ""),
        installation_date=installation_date,
        meter_brand=manufacturer,
        meter_model=model,
        meter_diameter=str(meter.get("meterDiameterCode") or ""),
        telereleve_tech=str(meter.get("pairingTechnologyCode") or ""),
    )


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert value to float, returning default on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _iter_months(start_date: date, end_date: date) -> list[tuple[int, int]]:
    """Return calendar months intersecting the inclusive date range."""
    if end_date < start_date:
        return []
    year, month = start_date.year, start_date.month
    result: list[tuple[int, int]] = []
    while (year, month) <= (end_date.year, end_date.month):
        result.append((year, month))
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return result


def _estimate_index_from_monthly(
    physical_index_m3: float,
    reading_date: date,
    through_date: date,
    monthly_payloads: list[dict[str, Any]],
) -> float | None:
    """Add daily consumption after a physical reading to its absolute index."""
    if through_date <= reading_date:
        return round(physical_index_m3, 3)
    total_m3 = 0.0
    for raw in monthly_payloads:
        consumptions = raw.get("consumptions")
        if not isinstance(consumptions, list):
            return None
        for item in consumptions:
            if not isinstance(item, dict) or item.get("rangeType") != "Day":
                continue
            try:
                entry_date = date.fromisoformat(str(item.get("startDate", ""))[:10])
            except (TypeError, ValueError):
                return None
            if not reading_date < entry_date <= through_date:
                continue
            try:
                value_m3 = float(item.get("value"))
            except (TypeError, ValueError):
                return None
            if value_m3 < 0:
                return None
            total_m3 += value_m3
    return round(physical_index_m3 + total_m3, 3)


def _has_nonzero_day(raw: dict[str, Any]) -> bool:
    """Return True if the response contains at least one Day entry with value > 0."""
    return any(
        isinstance(c, dict) and c.get("rangeType") == "Day" and _safe_float(c.get("value")) > 0
        for c in raw.get("consumptions", [])
    )


def _extract_latest_daily(raw: dict[str, Any]) -> tuple[float | None, date | None]:
    """Return the latest dated non-zero daily consumption and its date."""
    consumptions = raw.get("consumptions", [])
    if not isinstance(consumptions, list):
        return None, None

    latest: tuple[date, float] | None = None
    for item in consumptions:
        if not isinstance(item, dict) or item.get("rangeType") != "Day":
            continue
        value = _safe_float(item.get("value"))
        if value <= 0:
            continue
        try:
            entry_date = date.fromisoformat(str(item.get("startDate", ""))[:10])
        except (TypeError, ValueError):
            continue
        if latest is None or entry_date > latest[0]:
            latest = (entry_date, value)

    if latest is None:
        return None, None
    return round(latest[1] * 1000, 1), latest[0]


def _extract_daily_liters(raw: dict[str, Any]) -> float | None:
    """Extract the latest dated non-zero daily consumption in litres."""
    daily_liters, _ = _extract_latest_daily(raw)
    return daily_liters


def _extract_week_total_from_monthly(raw: dict[str, Any], ref_date: date) -> float | None:
    """Sum Day entries from the ISO week containing ref_date."""
    consumptions = raw.get("consumptions", [])
    if not isinstance(consumptions, list):
        return None
    monday = ref_date - timedelta(days=ref_date.weekday())
    sunday = monday + timedelta(days=6)
    values: list[float] = []
    for item in consumptions:
        if not isinstance(item, dict) or item.get("rangeType") != "Day":
            continue
        value = _safe_float(item.get("value"))
        if value <= 0:
            continue
        try:
            entry_date = date.fromisoformat(str(item.get("startDate", ""))[:10])
        except (ValueError, TypeError):
            continue
        if monday <= entry_date <= sunday:
            values.append(value)
    return round(sum(values), 3) if values else None


def _extract_week_total_m3(raw: dict[str, Any]) -> float | None:
    """Sum all non-zero Day entries in a weekly response."""
    consumptions = raw.get("consumptions", [])
    if not isinstance(consumptions, list):
        return None
    values = [
        _safe_float(c.get("value"))
        for c in consumptions
        if isinstance(c, dict) and c.get("rangeType") == "Day" and _safe_float(c.get("value")) > 0
    ]
    return round(sum(values), 3) if values else None


def _extract_period_m3(raw: dict[str, Any]) -> float | None:
    """Extract total consumption for a period."""
    consumptions = raw.get("consumptions", [])
    if not isinstance(consumptions, list) or not consumptions:
        value = raw.get("value") or raw.get("total") or raw.get("volume")
        if value is not None and float(value) >= 0:
            return round(float(value), 3)
        return None
    total = sum(
        float(c.get("value", 0))
        for c in consumptions
        if isinstance(c, dict) and float(c.get("value", 0)) >= 0
    )
    return round(total, 3)


def _parse_consumption(
    subscription_id: str,
    raw: dict[str, Any] | list[Any],
    fetched_at: datetime,
) -> SauronData:
    """Legacy parser kept for test backward-compatibility."""
    daily_liters: float | None = None
    if isinstance(raw, list) and raw:
        latest = raw[-1]
        if len(raw) >= 2:
            prev = raw[-2]
            prev_val = float(prev.get("index") or prev.get("value") or prev.get("volume") or 0.0)
            curr_val = float(
                latest.get("index") or latest.get("value") or latest.get("volume") or 0.0
            )
            delta_m3 = curr_val - prev_val
            if delta_m3 >= 0:
                daily_liters = round(delta_m3 * 1000, 1)
    elif isinstance(raw, dict):
        latest = raw
        daily_raw = raw.get("dailyConsumption") or raw.get("daily_volume") or raw.get("volumeJour")
        if daily_raw is not None:
            daily_liters = round(float(daily_raw) * 1000, 1)
    else:
        raise SauronNoDataError("Empty consumption payload")
    value_m3 = float(latest.get("index") or latest.get("value") or latest.get("volume") or 0.0)
    raw_date = latest.get("date") or latest.get("readingDate") or latest.get("dateRelevee")
    try:
        reading_date = date.fromisoformat(str(raw_date)[:10]) if raw_date else fetched_at.date()
    except (ValueError, TypeError):
        reading_date = fetched_at.date()
    meter_info = MeterInfo(
        subscription_id=subscription_id,
        address=str(latest.get("address") or latest.get("adresse") or ""),
        meter_serial=str(latest.get("meterSerial") or latest.get("serialNumber") or ""),
        installation_date=None,
    )
    reading = MeterReading(
        subscription_id=subscription_id,
        value_m3=value_m3,
        reading_date=reading_date,
        fetched_at=fetched_at,
    )
    return SauronData(
        meter_info=meter_info,
        latest_reading=reading,
        daily_liters=daily_liters,
    )
