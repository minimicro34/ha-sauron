"""Regression tests for endpoint rejection after successful token refresh."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from custom_components.sauron.api.client import SauronApiClient, TokenCache
from custom_components.sauron.api.exceptions import SauronAuthError, SauronTransientError


@pytest.mark.asyncio
async def test_fresh_token_rejected_is_transient_not_reauth() -> None:
    """A data endpoint 403 must not invalidate successfully authenticated credentials."""
    client = object.__new__(SauronApiClient)
    client._cache = TokenCache("expired", 0, "client", "section")
    client._auth_lock = asyncio.Lock()
    client._ensure_token = AsyncMock(return_value="expired")
    fresh = TokenCache("fresh", 9999999999, "client", "section")

    async def authenticate() -> None:
        client._cache = fresh

    client.async_authenticate = AsyncMock(side_effect=authenticate)
    client._do_get = AsyncMock(side_effect=[(401, None), (403, None)])

    with pytest.raises(SauronTransientError, match="rejected fresh token"):
        await client._get("/deli/section_subscription/123/consumptions/monthly")

    client.async_authenticate.assert_awaited_once()
    assert client._cache is fresh


@pytest.mark.asyncio
async def test_invalid_credentials_during_refresh_still_require_reauth() -> None:
    """Only the authentication endpoint's credential rejection is fatal."""
    client = object.__new__(SauronApiClient)
    client._cache = TokenCache("expired", 0, "client", "section")
    client._auth_lock = asyncio.Lock()
    client._ensure_token = AsyncMock(return_value="expired")
    client._do_get = AsyncMock(return_value=(401, None))
    client.async_authenticate = AsyncMock(
        side_effect=SauronAuthError("Invalid SAUR credentials")
    )

    with pytest.raises(SauronAuthError, match="Invalid SAUR credentials"):
        await client._get("/deli/section_subscription/123/consumptions/monthly")


@pytest.mark.asyncio
async def test_refresh_recovers_when_fresh_token_accepted() -> None:
    client = object.__new__(SauronApiClient)
    client._cache = TokenCache("expired", 0, "client", "section")
    client._auth_lock = asyncio.Lock()
    client._ensure_token = AsyncMock(return_value="expired")
    fresh = TokenCache("fresh", 9999999999, "client", "section")

    async def authenticate() -> None:
        client._cache = fresh

    client.async_authenticate = AsyncMock(side_effect=authenticate)
    client._do_get = AsyncMock(side_effect=[(401, None), (200, {"ok": True})])

    assert await client._get("/deli/section_subscription/123/consumptions/monthly") == {
        "ok": True
    }
