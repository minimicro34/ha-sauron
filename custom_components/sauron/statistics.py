"""Build dated, idempotently replaceable water statistics from SAUR daily readings."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from typing import Any
from zoneinfo import ZoneInfo


def build_daily_statistics(
    payloads: list[dict[str, Any]],
    reading_date: date,
    through_date: date,
    timezone: str,
    *,
    initial_sum: float = 0.0,
) -> list[dict[str, Any]]:
    """Build hourly Recorder rows at 23:00 local time, cumulative from the reading.

    Rebuilding the entire series ensures that a corrected historical day also
    updates all later sums. Missing days are not treated as zero: no row is
    written until SAUR supplies a complete consecutive history.
    """
    values: dict[date, float] = {}
    for payload in payloads:
        entries = payload.get("consumptions")
        if not isinstance(entries, list):
            raise ValueError("Invalid SAUR monthly consumptions")
        for item in entries:
            if not isinstance(item, dict) or item.get("rangeType") != "Day":
                continue
            try:
                day = date.fromisoformat(str(item["startDate"])[:10])
                value = float(item["value"])
            except (KeyError, TypeError, ValueError) as err:
                raise ValueError("Invalid SAUR daily reading") from err
            if value < 0 or value != value or value == float("inf"):
                raise ValueError("Invalid SAUR daily volume")
            if reading_date < day <= through_date:
                if day in values and values[day] != value:
                    raise ValueError("Conflicting SAUR readings for the same date")
                values[day] = value

    if values:
        ordered = sorted(values)
        if ordered[0] != reading_date + timedelta(days=1) or any(
            right - left != timedelta(days=1)
            for left, right in pairwise(ordered)
        ):
            raise ValueError("Incomplete SAUR daily history: missing dates")

    tz = ZoneInfo(timezone)
    if initial_sum < 0 or not float("-inf") < initial_sum < float("inf"):
        raise ValueError("Invalid initial cumulative sum")
    total = initial_sum
    rows: list[dict[str, Any]] = []
    for day in sorted(values):
        total = round(total + values[day], 6)
        rows.append(
            {
                "start": datetime.combine(day, time(hour=23), tzinfo=tz).astimezone(UTC),
                "state": round(values[day], 6),
                "sum": total,
            }
        )
    return rows


def merge_daily_history(
    existing: dict[str, float],
    payloads: list[dict[str, Any]],
    reading_date: date,
    through_date: date,
) -> dict[str, float]:
    """Merge a new meter-reading period into a continuous, gap-free daily ledger.

    Previously imported days are retained across physical meter readings.
    Existing values are only changed if SAUR supplies a corrected day again.
    """
    if existing:
        last = max(date.fromisoformat(key) for key in existing)
        # The previous ledger date, not the new physical reading, is the
        # continuity anchor. The coordinator must fetch every month since it.
        start = last
    else:
        start = reading_date

    rows = build_daily_statistics(payloads, start, through_date, "UTC")
    merged = dict(existing)
    for row in rows:
        day = row["start"].date().isoformat()
        merged[day] = row["state"]
    if merged:
        ordered = sorted(date.fromisoformat(key) for key in merged)
        if any(right - left != timedelta(days=1) for left, right in pairwise(ordered)):
            raise ValueError("Incomplete SAUR daily history: missing dates")
    return merged


def build_ledger_statistics(
    daily_values: dict[str, float], timezone: str
) -> list[dict[str, Any]]:
    """Rebuild the complete continuous Recorder series after a new reading."""
    if not daily_values:
        return []
    days = sorted(date.fromisoformat(key) for key in daily_values)
    baseline = days[0] - timedelta(days=1)
    return build_daily_statistics(
        [
            {
                "consumptions": [
                    {
                        "rangeType": "Day",
                        "startDate": day.isoformat(),
                        "value": daily_values[day.isoformat()],
                    }
                    for day in days
                ]
            }
        ],
        baseline,
        days[-1],
        timezone,
    )
