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


class SauronCoordinator(DataUpdateCoordinator[SauronData]):
    """Fetch SAUR water consumption data on a configurable schedule."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        client: SauronApiClient,
        entry: ConfigEntry,
    ) -> None:
        scan_interval_h = entry.options.get(OPT_SCAN_INTERVAL_H, DEFAULT_SCAN_INTERVAL_H)
        super().__init__(
            hass,
            _LOGGER,
            name=f"SAURon ({entry.data[CONF_SUBSCRIPTION_ID]})",
            update_interval=timedelta(hours=scan_interval_h),
            config_entry=entry,
            always_update=False,
        )
        self._client = client
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

        # Primary: latest physical meter index.
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

        # Build a cumulative estimated index from the latest physical reading.
        # When SAUR publishes a newer physical reading (typically after a technician
        # visit), that new value/date automatically becomes the baseline and the
        # accumulated consumption starts again strictly after that reading date.
        estimated_index_m3 = await self._async_estimated_index(
            subscription_id,
            data.latest_reading,
            yesterday,
        )

        # Enrich: monthly response — single call covers daily, weekly, and monthly sensors.
        # SAUR /consumptions/monthly returns every day of the month as a Day entry,
        # pre-populated with value=0 for future days. We derive:
        #   daily_liters  — last Day entry with value > 0
        #   weekly_m3     — sum of Day entries whose startDate falls in the current ISO week
        #   monthly_m3    — sum of all non-zero Day entries
        # On days 1-2 of a new month yesterday may still be in the previous month, so we
        # fall back to the previous month's data when the current month has no entries yet.
        raw_monthly: dict[str, Any] = {}
        try:
            raw_monthly = await self._client.async_get_monthly(
                subscription_id, now.year, now.month
            )
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

        daily_liters = _extract_daily_liters(raw_monthly)
        weekly_m3 = _extract_week_total_from_monthly(raw_monthly, yesterday)
        monthly_m3 = _extract_period_m3(raw_monthly)

        # Enrich: yearly consumption.
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
            weekly_m3=weekly_m3,
            monthly_m3=monthly_m3,
            yearly_m3=yearly_m3,
        )

        # Manage stale-data Repair Issue.
        reading_age_h = (
            (now.date() - enriched.latest_reading.reading_date).days * 24
            + now.hour
        )
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
        self,
        subscription_id: str,
        reading: MeterReading,
        through_date: date,
    ) -> float | None:
        """Estimate the current cumulative index from daily SAUR consumption data."""
        if through_date <= reading.reading_date:
            return round(reading.value_m3, 3)

        monthly_payloads: list[dict[str, Any]] = []
        for year, month in _iter_months(reading.reading_date, through_date):
            try:
                payload = await self._client.async_get_monthly(
                    subscription_id, year, month
                )
            except SauronAuthError as err:
                raise ConfigEntryAuthFailed from err
            except SauronTransientError as err:
                _LOGGER.warning(
                    "Could not build estimated water index for %s: monthly data "
                    "%04d-%02d is temporarily unavailable: %s",
                    subscription_id,
                    year,
                    month,
                    err,
                )
                return None
            except Exception as err:
                _LOGGER.warning(
                    "Could not build estimated water index for %s: monthly data "
                    "%04d-%02d failed: %s",
                    subscription_id,
                    year,
                    month,
                    err,
                )
                return None
            monthly_payloads.append(payload)

        estimated = _estimate_index_from_monthly(
            reading.value_m3,
            reading.reading_date,
            through_date,
            monthly_payloads,
        )
        if estimated is None:
            _LOGGER.warning(
                "Could not build estimated water index for %s: incomplete monthly payload",
                subscription_id,
            )
        return estimated


def _parse_last_index(
    subscription_id: str,
    raw: dict[str, Any],
    fetched_at: datetime,
    meter_info: MeterInfo | None = None,
) -> SauronData:
    """Parse GET /meter_indexes/last response.

    Real API response shape:
      { "readingDate": "2026-06-15T00:00:00", "indexValue": 1234.567 }
    """
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
        meter_info = MeterInfo(
            subscription_id=subscription_id,
            address="",
            meter_serial="",
            installation_date=None,
        )
    reading = MeterReading(
        subscription_id=subscription_id,
        value_m3=float(index_value),
        reading_date=reading_date,
        fetched_at=fetched_at,
    )
    return SauronData(meter_info=meter_info, latest_reading=reading)


def _parse_delivery_points(subscription_id: str, raw: dict[str, Any]) -> MeterInfo:
    """Parse GET /deli/section_subscriptions/{id}/supply_areas/delivery_points.

    Real API response shape (single dict, not a list):
      { "meter": { "serialNumber": "...", "meterBrandCode": "...", ... },
        "geographicAddress": { "city": "...", "streetAddress": "...", ... } }
    """
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

    city = str(addr.get("city") or "")
    address = city

    return MeterInfo(
        subscription_id=subscription_id,
        address=address,
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

    year = start_date.year
    month = start_date.month
    result: list[tuple[int, int]] = []
    while (year, month) <= (end_date.year, end_date.month):
        result.append((year, month))
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    return result


def _estimate_index_from_monthly(
    physical_index_m3: float,
    reading_date: date,
    through_date: date,
    monthly_payloads: list[dict[str, Any]],
) -> float | None:
    """Add daily consumption after a physical reading to its absolute index.

    The physical reading day itself is deliberately excluded because the reading
    already represents the meter state on that date. Only Day entries strictly
    after ``reading_date`` and up to ``through_date`` are accumulated.
    """
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
                value_m3 = float(item.get("value"))
            except (TypeError, ValueError):
                return None

            if value_m3 < 0:
                return None
            if reading_date < entry_date <= through_date:
                total_m3 += value_m3

    return round(physical_index_m3 + total_m3, 3)


def _has_nonzero_day(raw: dict[str, Any]) -> bool:
    """Return True if the response contains at least one Day entry with value > 0."""
    return any(
        isinstance(c, dict) and c.get("rangeType") == "Day" and _safe_float(c.get("value")) > 0
        for c in raw.get("consumptions", [])
    )


def _extract_daily_liters(raw: dict[str, Any]) -> float | None:
    """Extract the most recent non-zero daily consumption in litres from a monthly response.

    Real API response shape (from /consumptions/monthly):
      { "consumptions": [{ "startDate": "...", "value": 0.085, "rangeType": "Day" }] }

    Takes the last Day entry with value > 0 (future days are pre-populated with 0).
    Returns None if no non-zero Day entry found.
    """
    consumptions = raw.get("consumptions", [])
    if not isinstance(consumptions, list):
        return None

    day_entries = [
        c
        for c in consumptions
        if isinstance(c, dict)
        and c.get("rangeType") == "Day"
        and _safe_float(c.get("value")) > 0
    ]
    if not day_entries:
        return None

    value_m3 = day_entries[-1].get("value")
    if value_m3 is None:
        return None
    return round(_safe_float(value_m3) * 1000, 1)


def _extract_week_total_from_monthly(raw: dict[str, Any], ref_date: date) -> float | None:
    """Sum Day entries from the ISO week containing ref_date, using a monthly response.

    ref_date is typically yesterday (J-1). We sum only entries whose startDate falls
    in the same ISO week (Monday to Sunday) as ref_date.
    """
    consumptions = raw.get("consumptions", [])
    if not isinstance(consumptions, list):
        return None

    monday = ref_date - timedelta(days=ref_date.weekday())
    sunday = monday + timedelta(days=6)

    week_entries = []
    for c in consumptions:
        if not isinstance(c, dict) or c.get("rangeType") != "Day":
            continue
        value = _safe_float(c.get("value"))
        if value <= 0:
            continue
        try:
            entry_date = date.fromisoformat(str(c.get("startDate", ""))[:10])
        except (ValueError, TypeError):
            continue
        if monday <= entry_date <= sunday:
            week_entries.append(value)

    if not week_entries:
        return None
    return round(sum(week_entries), 3)


def _extract_week_total_m3(raw: dict[str, Any]) -> float | None:
    """Sum all non-zero Day entries in a weekly response to get total week volume in m³.

    Kept for backward-compatibility with existing tests.
    """
    consumptions = raw.get("consumptions", [])
    if not isinstance(consumptions, list):
        return None

    day_entries = [
        c
        for c in consumptions
        if isinstance(c, dict)
        and c.get("rangeType") == "Day"
        and _safe_float(c.get("value")) > 0
    ]
    if not day_entries:
        return None

    total = sum(_safe_float(c.get("value")) for c in day_entries)
    return round(total, 3)


def _extract_period_m3(raw: dict[str, Any]) -> float | None:
    """Extract total consumption for a period (monthly or yearly response).

    The response may contain a single value or a list of sub-periods.
    We sum all non-negative values.
    """
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
    """Legacy parser kept for test backward-compat. See _parse_last_index for current usage."""
    daily_liters: float | None = None

    if isinstance(raw, list) and raw:
        latest = raw[-1]
        if len(raw) >= 2:
            prev = raw[-2]
            prev_val = float(
                prev.get("index") or prev.get("value") or prev.get("volume") or 0.0
            )
            curr_val = float(
                latest.get("index") or latest.get("value") or latest.get("volume") or 0.0
            )
            delta_m3 = curr_val - prev_val
            if delta_m3 >= 0:
                daily_liters = round(delta_m3 * 1000, 1)
    elif isinstance(raw, dict):
        latest = raw
        daily_raw = (
            raw.get("dailyConsumption")
            or raw.get("daily_volume")
            or raw.get("volumeJour")
        )
        if daily_raw is not None:
            daily_liters = round(float(daily_raw) * 1000, 1)
    else:
        raise SauronNoDataError("Empty consumption payload")

    value_m3 = float(
        latest.get("index") or latest.get("value") or latest.get("volume") or 0.0
    )
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
