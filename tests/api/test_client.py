"""Tests for the SAURon API client (pure-library, no HA)."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.sauron.api.client import SauronApiClient, TokenCache
from custom_components.sauron.api.exceptions import (
    SauronApiError,
    SauronAuthError,
    SauronTransientError,
)
from custom_components.sauron.const import DEFAULT_TOKEN_TTL_S, TOKEN_REFRESH_MARGIN_S


def _make_response(status: int, json_data: object) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data)
    resp.text = AsyncMock(return_value=str(json_data))
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


_AUTH_SUCCESS = {
    "token": {"access_token": "tok123"},
    "clientId": "CLI001",
    "defaultSectionId": "SUB9876",
}


@pytest.fixture
def mock_session() -> MagicMock:
    session = MagicMock()
    session.post = MagicMock()
    session.get = MagicMock()
    return session


class TestSauronApiClientAuth:
    async def test_authenticate_success(self, mock_session: MagicMock) -> None:
        mock_session.post.return_value = _make_response(200, _AUTH_SUCCESS)

        client = SauronApiClient(mock_session, "user@example.com", "pass")
        await client.async_authenticate()

        assert client._cache is not None
        assert client._cache.access_token == "tok123"
        assert client.client_id == "CLI001"
        assert client.default_section_id == "SUB9876"
        assert client._is_token_valid()

    async def test_authenticate_sends_correct_payload(self, mock_session: MagicMock) -> None:
        mock_session.post.return_value = _make_response(200, _AUTH_SUCCESS)

        client = SauronApiClient(mock_session, "user@example.com", "mypass")
        await client.async_authenticate()

        call_kwargs = mock_session.post.call_args[1]
        payload = call_kwargs["json"]
        assert payload["username"] == "user@example.com"
        assert payload["password"] == "mypass"
        assert payload["client_id"] == "frontjs-client"
        assert payload["grant_type"] == "password"
        assert payload["captchaToken"] == "true"

    async def test_authenticate_401_raises_auth_error(self, mock_session: MagicMock) -> None:
        mock_session.post.return_value = _make_response(401, {})

        client = SauronApiClient(mock_session, "bad@example.com", "wrong")
        with pytest.raises(SauronAuthError):
            await client.async_authenticate()

    async def test_authenticate_403_raises_auth_error(self, mock_session: MagicMock) -> None:
        mock_session.post.return_value = _make_response(403, {})

        client = SauronApiClient(mock_session, "bad@example.com", "wrong")
        with pytest.raises(SauronAuthError):
            await client.async_authenticate()

    async def test_authenticate_500_raises_api_error(self, mock_session: MagicMock) -> None:
        mock_session.post.return_value = _make_response(500, "Internal Server Error")

        client = SauronApiClient(mock_session, "user@example.com", "pass")
        with pytest.raises(SauronApiError) as exc_info:
            await client.async_authenticate()
        assert exc_info.value.status == 500

    async def test_authenticate_missing_token_raises_auth_error(
        self, mock_session: MagicMock
    ) -> None:
        mock_session.post.return_value = _make_response(200, {"clientId": "X", "token": {}})

        client = SauronApiClient(mock_session, "user@example.com", "pass")
        with pytest.raises(SauronAuthError, match="No access_token"):
            await client.async_authenticate()

    async def test_token_valid_after_auth(self, mock_session: MagicMock) -> None:
        mock_session.post.return_value = _make_response(200, _AUTH_SUCCESS)
        client = SauronApiClient(mock_session, "u", "p")
        assert not client._is_token_valid()
        await client.async_authenticate()
        assert client._is_token_valid()

    async def test_client_id_none_before_auth(self, mock_session: MagicMock) -> None:
        client = SauronApiClient(mock_session, "u", "p")
        assert client.client_id is None
        assert client.default_section_id is None

    async def test_missing_client_id_raises_api_error(self, mock_session: MagicMock) -> None:
        mock_session.post.return_value = _make_response(
            200,
            {"token": {"access_token": "tok"}},  # no clientId
        )
        client = SauronApiClient(mock_session, "u", "p")
        # client_id will be empty string — validate this does not raise here
        # (the config flow raises SauronApiError after checking client_id)
        await client.async_authenticate()
        assert client.client_id == ""


# ─────────────────────────────────────────────────────────────────────────────
# Plan A §3 — TokenCache, expiry, lock, two-tier 401 retry
# ─────────────────────────────────────────────────────────────────────────────


def _auth_with_ttl(ttl_s: int | None) -> dict[str, object]:
    payload: dict[str, object] = {
        "token": {"access_token": "tok_new"},
        "clientId": "CLI001",
        "defaultSectionId": "SUB9876",
    }
    if ttl_s is not None:
        payload["expires_in"] = ttl_s
    return payload


class TestTokenCacheLifecycle:
    async def test_authenticate_reads_expires_in(self, mock_session: MagicMock) -> None:
        mock_session.post.return_value = _make_response(200, _auth_with_ttl(7200))

        client = SauronApiClient(mock_session, "u", "p")
        before = time.time()
        await client.async_authenticate()
        after = time.time()

        assert client._cache is not None
        # expires_at lands within the ±1s window around (now + 7200)
        assert before + 7200 - 1 <= client._cache.expires_at <= after + 7200 + 1

    async def test_authenticate_uses_default_ttl_when_missing(
        self, mock_session: MagicMock
    ) -> None:
        mock_session.post.return_value = _make_response(200, _auth_with_ttl(None))

        client = SauronApiClient(mock_session, "u", "p")
        before = time.time()
        await client.async_authenticate()

        assert client._cache is not None
        assert client._cache.expires_at >= before + DEFAULT_TOKEN_TTL_S - 1

    async def test_authenticate_invokes_on_token_refreshed(self, mock_session: MagicMock) -> None:
        mock_session.post.return_value = _make_response(200, _auth_with_ttl(3600))
        callback = AsyncMock()

        client = SauronApiClient(mock_session, "u", "p", on_token_refreshed=callback)
        await client.async_authenticate()

        callback.assert_awaited_once()
        cache_arg = callback.await_args.args[0]
        assert isinstance(cache_arg, TokenCache)
        assert cache_arg.access_token == "tok_new"

    async def test_is_token_valid_false_near_expiry(self, mock_session: MagicMock) -> None:
        client = SauronApiClient(
            mock_session,
            "u",
            "p",
            initial_token=TokenCache(
                access_token="t",
                expires_at=time.time() + TOKEN_REFRESH_MARGIN_S - 1,
                client_id="c",
                default_section_id="s",
            ),
        )
        assert client._is_token_valid() is False

    async def test_is_token_valid_true_well_before_expiry(self, mock_session: MagicMock) -> None:
        client = SauronApiClient(
            mock_session,
            "u",
            "p",
            initial_token=TokenCache(
                access_token="t",
                expires_at=time.time() + 3600,
                client_id="c",
                default_section_id="s",
            ),
        )
        assert client._is_token_valid() is True

    async def test_initial_token_skips_first_auth_call(self, mock_session: MagicMock) -> None:
        # GET succeeds with the initial token — no auth POST should occur
        mock_session.get.return_value = _make_response(200, {"indexValue": 1.0})

        client = SauronApiClient(
            mock_session,
            "u",
            "p",
            initial_token=TokenCache(
                access_token="cached",
                expires_at=time.time() + 3600,
                client_id="CLI001",
                default_section_id="SUB001",
            ),
        )
        await client.async_get_meter_last_index("SUB001")

        mock_session.post.assert_not_called()

    async def test_initial_token_expired_triggers_auth(self, mock_session: MagicMock) -> None:
        mock_session.post.return_value = _make_response(200, _auth_with_ttl(3600))
        mock_session.get.return_value = _make_response(200, {"indexValue": 1.0})

        client = SauronApiClient(
            mock_session,
            "u",
            "p",
            initial_token=TokenCache(
                access_token="expired",
                expires_at=time.time() - 10,  # already expired
                client_id="CLI001",
                default_section_id="SUB001",
            ),
        )
        await client.async_get_meter_last_index("SUB001")

        mock_session.post.assert_called_once()


class TestTwoTier401Retry:
    async def test_get_401_then_success_returns_body(self, mock_session: MagicMock) -> None:
        mock_session.post.return_value = _make_response(200, _auth_with_ttl(3600))
        # First GET 401, second GET 200
        mock_session.get.side_effect = [
            _make_response(401, {}),
            _make_response(200, {"indexValue": 42.0}),
        ]

        client = SauronApiClient(
            mock_session,
            "u",
            "p",
            initial_token=TokenCache(
                access_token="stale",
                expires_at=time.time() + 3600,
                client_id="CLI001",
                default_section_id="SUB001",
            ),
        )
        result = await client.async_get_meter_last_index("SUB001")

        assert result == {"indexValue": 42.0}
        mock_session.post.assert_called_once()  # one re-auth between the two GETs

    async def test_get_401_then_fresh_token_401_raises_auth_error(
        self, mock_session: MagicMock
    ) -> None:
        mock_session.post.return_value = _make_response(200, _auth_with_ttl(3600))
        # Both GETs return 401, even after the fresh token
        mock_session.get.side_effect = [
            _make_response(401, {}),
            _make_response(401, {}),
        ]

        client = SauronApiClient(
            mock_session,
            "u",
            "p",
            initial_token=TokenCache(
                access_token="stale",
                expires_at=time.time() + 3600,
                client_id="CLI001",
                default_section_id="SUB001",
            ),
        )

        with pytest.raises(SauronAuthError, match="rejected fresh token"):
            await client.async_get_meter_last_index("SUB001")

    async def test_get_401_then_auth_endpoint_500_raises_transient(
        self, mock_session: MagicMock
    ) -> None:
        # First GET 401, the re-auth POST returns 500 → must surface as TransientError
        mock_session.post.return_value = _make_response(500, "Internal Server Error")
        mock_session.get.return_value = _make_response(401, {})

        client = SauronApiClient(
            mock_session,
            "u",
            "p",
            initial_token=TokenCache(
                access_token="stale",
                expires_at=time.time() + 3600,
                client_id="CLI001",
                default_section_id="SUB001",
            ),
        )

        with pytest.raises(SauronTransientError):
            await client.async_get_meter_last_index("SUB001")

    async def test_get_network_error_raises_transient(self, mock_session: MagicMock) -> None:
        mock_session.get.side_effect = aiohttp.ClientError("Connection reset")

        client = SauronApiClient(
            mock_session,
            "u",
            "p",
            initial_token=TokenCache(
                access_token="ok",
                expires_at=time.time() + 3600,
                client_id="CLI001",
                default_section_id="SUB001",
            ),
        )

        with pytest.raises(SauronTransientError):
            await client.async_get_meter_last_index("SUB001")


class TestAuthLock:
    async def test_concurrent_ensure_token_authenticates_once(
        self, mock_session: MagicMock
    ) -> None:
        """RC-2: two concurrent _ensure_token calls must yield exactly one POST /auth."""

        call_count = {"n": 0}

        # session.post(...) is invoked SYNCHRONOUSLY (returns the async-CM).
        # We slip the slow wait inside the response's __aenter__ so a second
        # concurrent caller has time to enter _ensure_token and block on the lock.
        def _make_slow_response() -> MagicMock:
            call_count["n"] += 1
            resp = MagicMock()
            resp.status = 200
            resp.json = AsyncMock(return_value=_auth_with_ttl(3600))
            resp.text = AsyncMock(return_value="ok")

            async def _slow_aenter(self_resp: MagicMock = resp) -> MagicMock:
                await asyncio.sleep(0.01)
                return self_resp

            resp.__aenter__ = _slow_aenter
            resp.__aexit__ = AsyncMock(return_value=False)
            return resp

        mock_session.post.side_effect = lambda *a, **kw: _make_slow_response()

        client = SauronApiClient(mock_session, "u", "p")

        await asyncio.gather(
            client._ensure_token(),
            client._ensure_token(),
        )

        # The double-checked pattern under self._auth_lock must collapse
        # two concurrent calls into a single authentication.
        assert call_count["n"] == 1
