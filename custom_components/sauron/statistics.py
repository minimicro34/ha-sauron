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
) -> list[dict[str, Any]]:
    """Build hourly Recorder rows at 23:00 local time, cumulative from the reading.

    Rebuilding the entire series ensures that a corrected historical day also
    updates all later sums. Missing days are not treated as zero: no row is
    written for them until SAUR supplies a dated value.
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
    total = 0.0
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
