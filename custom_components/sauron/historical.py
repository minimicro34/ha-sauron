"""Read-only preparation of a historical SAUR daily-consumption import.

This module deliberately does NOT modify Recorder or the persisted daily ledger.
Historical sums must be reconciled before any backfill is enabled.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import isfinite
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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
    def available_ranges(self) -> tuple[tuple[str, str], ...]:
        """Contiguous intervals actually returned by SAUR, without inventing zeros."""
        days = sorted(date.fromisoformat(key) for key in self.values)
        if not days:
            return ()
        ranges: list[tuple[str, str]] = []
        first = previous = days[0]
        for day in days[1:]:
            if day - previous != timedelta(days=1):
                ranges.append((first.isoformat(), previous.isoformat()))
                first = day
            previous = day
        ranges.append((first.isoformat(), previous.isoformat()))
        return tuple(ranges)

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
        if not isinstance(payload, dict):
            raise ValueError("Invalid historical SAUR response")
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


def summarize_historical_coverage(
    preview: HistoricalPreview,
    existing: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Summarize a multi-month read-only preview and actual ledger overlap."""
    ledger = existing or {}
    months: list[dict[str, Any]] = []
    for year, month in _months(preview.start, preview.end):
        first = max(preview.start, date(year, month, 1))
        next_month = date(year + (month == 12), month % 12 + 1, 1)
        last = min(preview.end, next_month - timedelta(days=1))
        days = [
            (first + timedelta(days=offset)).isoformat()
            for offset in range((last - first).days + 1)
        ]
        returned = sum(day in preview.values for day in days)
        months.append({
            "month": f"{year:04d}-{month:02d}",
            "expected_days": len(days),
            "returned_days": returned,
            "missing_days": len(days) - returned,
            "ledger_overlap_days": sum(day in ledger and day in preview.values for day in days),
            "ledger_conflicts": sum(day in preview.conflicts_with_ledger for day in days),
        })
    overlaps = sorted(set(preview.values).intersection(ledger))
    return {
        "start": preview.start.isoformat(),
        "end": preview.end.isoformat(),
        "expected_days": (preview.end - preview.start).days + 1,
        "returned_days": len(preview.values),
        "missing_days_count": len(preview.missing_days),
        "missing_days": list(preview.missing_days),
        "available_ranges": [list(item) for item in preview.available_ranges],
        "months": months,
        "ledger_available": bool(ledger),
        "ledger_days": len(ledger),
        "ledger_first_day": min(ledger) if ledger else None,
        "ledger_last_day": max(ledger) if ledger else None,
        "ledger_overlap_days": len(overlaps),
        "ledger_conflicts": {
            key: {"existing": old, "received": new}
            for key, (old, new) in preview.conflicts_with_ledger.items()
        },
        "recorder_verified": False,
        "recorder_note": (
            "Recorder long-term statistics are NOT compared by this action. "
            "Ledger overlap alone cannot establish Recorder consistency."
        ),
        "complete": preview.complete,
        "read_only": True,
    }
