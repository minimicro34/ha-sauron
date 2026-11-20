"""Regression tests for stable-month SAUR response caching."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.sauron.coordinator import SauronCoordinator


def _coordinator(side_effect=None):
    coordinator = object.__new__(SauronCoordinator)
    coordinator._monthly_cache = {}
    coordinator._client = SimpleNamespace(
        async_get_monthly=AsyncMock(side_effect=side_effect)
        if side_effect is not None
        else AsyncMock(return_value={"consumptions": [{"value": 0.1}]})
    )
    return coordinator


@pytest.mark.asyncio
async def test_historical_month_fetched_once_across_consumers():
    coordinator = _coordinator()
    first = await coordinator._async_monthly_cached("SUB001", 2026, 5)
    second = await coordinator._async_monthly_cached("SUB001", 2026, 5)
    assert first is second
    coordinator._client.async_get_monthly.assert_awaited_once_with("SUB001", 2026, 5)


@pytest.mark.asyncio
async def test_current_month_always_refetched():
    coordinator = _coordinator()
    now = datetime.now(UTC)
    await coordinator._async_monthly_cached("SUB001", now.year, now.month)
    await coordinator._async_monthly_cached("SUB001", now.year, now.month)
    assert coordinator._client.async_get_monthly.await_count == 2


@pytest.mark.asyncio
async def test_recent_completed_month_refetched():
    coordinator = _coordinator()
    today = datetime.now(UTC).date()
    recent = today.replace(day=1) - timedelta(days=1)
    if (today - recent).days > 35:
        pytest.skip("Last completed month is outside correction window")
    await coordinator._async_monthly_cached("SUB001", recent.year, recent.month)
    await coordinator._async_monthly_cached("SUB001", recent.year, recent.month)
    assert coordinator._client.async_get_monthly.await_count == 2


@pytest.mark.asyncio
async def test_failed_historical_fetch_is_not_cached():
    coordinator = _coordinator(side_effect=[RuntimeError("HTTP 500"), {"consumptions": []}])
    with pytest.raises(RuntimeError, match="HTTP 500"):
        await coordinator._async_monthly_cached("SUB001", 2026, 5)
    assert coordinator._monthly_cache == {}
    assert await coordinator._async_monthly_cached("SUB001", 2026, 5) == {
        "consumptions": []
    }
    assert coordinator._client.async_get_monthly.await_count == 2


@pytest.mark.asyncio
async def test_cache_isolated_by_subscription():
    coordinator = _coordinator()
    await coordinator._async_monthly_cached("SUB001", 2026, 5)
    await coordinator._async_monthly_cached("SUB002", 2026, 5)
    assert coordinator._client.async_get_monthly.await_count == 2


@pytest.mark.asyncio
async def test_35_day_boundary():
    coordinator = _coordinator()
    # Freeze UTC time to test the exact correction-window boundary.
    today = datetime(2026, 11, 20, tzinfo=UTC)
    with patch("custom_components.sauron.coordinator.datetime") as clock:
        clock.now.return_value = today
        await coordinator._async_monthly_cached("SUB001", 2026, 10)
        await coordinator._async_monthly_cached("SUB001", 2026, 10)
        assert coordinator._client.async_get_monthly.await_count == 2
        await coordinator._async_monthly_cached("SUB001", 2026, 9)
        await coordinator._async_monthly_cached("SUB001", 2026, 9)
        assert coordinator._client.async_get_monthly.await_count == 3
