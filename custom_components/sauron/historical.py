"""Read-only preparation of a historical SAUR daily-consumption import.

This module deliberately does NOT modify Recorder or the persisted daily ledger.
Historical sums must be reconciled before any backfill is enabled.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import isfinite
from typing import Any

from .api import SauronApiClient


@dataclass(frozen=True)
class HistoricalPreview:
    """Validated daily data and coverage for a requested historical interval."""

    start: date
    end: date
    values: dict[str, float]
    missing_days: tuple[str, ...]
    conflicts_with_ledger: dict[str, tuple[float, float]]

    @property
    def complete(self) -> bool:
        """Whether every requested day is explicitly represented."""
        return not self.missing_days and not self.conflicts_with_ledger


def _months(start: date, end: date):
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield year, month
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def preview_monthly_payloads(
    payloads: list[dict[str, Any]],
    start: date,
    end: date,
    existing: dict[str, float] | None = None,
) -> HistoricalPreview:
    """Validate daily readings without converting missing days to zero.

    Repeated identical dates are fine; contradictory dates, negative/non-finite
    values and malformed API responses fail closed.
    """
    if start > end:
        raise ValueError("Historical start must not exceed end")
    values: dict[str, float] = {}
    for payload in payloads:
        entries = payload.get("consumptions")
        if not isinstance(entries, list):
            raise ValueError("Invalid historical SAUR response")
        for item in entries:
            if not isinstance(item, dict) or item.get("rangeType") != "Day":
                continue
            try:
                day = date.fromisoformat(str(item["startDate"])[:10])
                volume = float(item["value"])
            except (KeyError, TypeError, ValueError) as err:
                raise ValueError("Invalid historical SAUR daily reading") from err
            if not isfinite(volume) or volume < 0:
                raise ValueError("Invalid historical SAUR daily volume")
            if not start <= day <= end:
                continue
            key = day.isoformat()
            if key in values and values[key] != volume:
                raise ValueError(f"Conflicting historical SAUR reading for {key}")
            values[key] = volume

    missing: list[str] = []
    day = start
    while day <= end:
        key = day.isoformat()
        if key not in values:
            missing.append(key)
        day += timedelta(days=1)

    conflicts = {
        key: (float(old), value)
        for key, value in values.items()
        if (old := (existing or {}).get(key)) is not None and float(old) != value
    }
    return HistoricalPreview(start, end, values, tuple(missing), conflicts)


async def fetch_historical_preview(
    client: SauronApiClient,
    subscription_id: str,
    start: date,
    end: date,
    existing: dict[str, float] | None = None,
) -> HistoricalPreview:
    """Fetch historical months sequentially; never write to Home Assistant.

    SAUR's monthly endpoint must be verified to expose Day records for older
    years before any Recorder import can be implemented.
    """
    if start > end:
        raise ValueError("Historical start must not exceed end")
    payloads = [
        await client.async_get_monthly(subscription_id, year, month)
        for year, month in _months(start, end)
    ]
    return preview_monthly_payloads(payloads, start, end, existing)
