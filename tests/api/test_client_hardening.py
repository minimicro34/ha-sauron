"""Additional branch and endpoint coverage for the SAUR API client."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.sauron.api.client import SauronApiClient, TokenCache
from custom_components.sauron.api.exceptions import (
    SauronApiError,
    SauronAuthError,
    SauronNoDataError,
    SauronTransientError,
)
from custom_components.sauron.const import DEFAULT_TOKEN_TTL_S


def _response(status: int, payload: object) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=payload)
    resp.text = AsyncMock(return_value=str(payload))
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


def _valid_token(value: str = "cached") -> TokenCache:
    return TokenCache(
        access_token=value,
        expires_at=time.time() + 3600,
        client_id="CLI001",
        default_section_id="SUB001",
    )


def _client(session: MagicMock) -> SauronApiClient:
    return SauronApiClient(session, "u", "p", initial_token=_valid_token())


class TestAuthenticationEdgeCases:
    async def test_non_dict_token_payload_is_rejected(self) -> None:
        session = MagicMock()
        session.post.return_value = _response(
            200,
            {"token": "bad-token-shape", "clientId": "C", "defaultSectionId": "S"},
        )
        client = SauronApiClient(session, "u", "p")

        with pytest.raises(SauronAuthError, match="No access_token"):
            await client.async_authenticate()

    async def test_invalid_expires_in_uses_default_ttl(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = MagicMock()
        session.post.return_value = _response(
            200,
            {
                "token": {"access_token": "fresh"},
                "clientId": "C",
                "defaultSectionId": "S",
                "expires_in": "not-an-int",
            },
        )
        monkeypatch.setattr("custom_components.sauron.api.client.time.time", lambda: 1000.0)
        client = SauronApiClient(session, "u", "p")

        await client.async_authenticate()

        assert client._cache is not None
        assert client._cache.expires_at == 1000.0 + DEFAULT_TOKEN_TTL_S

    async def test_refresh_auth_error_is_preserved(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(401, {})
        session.post.return_value = _response(401, {})
        client = _client(session)

        with pytest.raises(SauronAuthError, match="Invalid SAUR credentials"):
            await client.async_get_meter_last_index("SUB001")


class TestSingleGetErrorMapping:
    async def test_http_500_is_transient(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(503, "maintenance")
        client = _client(session)

        with pytest.raises(SauronTransientError, match="HTTP 503"):
            await client.async_get_meter_last_index("SUB001")

    async def test_non_200_non_5xx_is_api_error(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(404, "missing")
        client = _client(session)

        with pytest.raises(SauronApiError) as exc_info:
            await client.async_get_meter_last_index("SUB001")

        assert exc_info.value.status == 404

    async def test_timeout_is_transient(self) -> None:
        session = MagicMock()
        session.get.side_effect = TimeoutError("slow")
        client = _client(session)

        with pytest.raises(SauronTransientError, match="Network error"):
            await client.async_get_meter_last_index("SUB001")

    async def test_aiohttp_error_is_transient(self) -> None:
        session = MagicMock()
        session.get.side_effect = aiohttp.ClientConnectionError("reset")
        client = _client(session)

        with pytest.raises(SauronTransientError, match="Network error"):
            await client.async_get_meter_last_index("SUB001")


class TestEndpointWrappers:
    async def test_website_areas_path(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(200, {"areas": []})
        client = _client(session)

        assert await client.async_get_website_areas("CLIENT42") == {"areas": []}
        assert "/admin/users/v2/website_areas/CLIENT42" in session.get.call_args.args[0]

    async def test_delivery_points_rejects_non_dict(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(200, [])
        client = _client(session)

        with pytest.raises(SauronNoDataError, match="Expected dict"):
            await client.async_get_delivery_points("SUB001")

    async def test_delivery_points_accepts_dict(self) -> None:
        session = MagicMock()
        payload = {"meter": {"serialNumber": "123"}}
        session.get.return_value = _response(200, payload)
        client = _client(session)

        assert await client.async_get_delivery_points("SUB001") == payload

    async def test_consumptions_endpoint(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(200, {"consumptions": []})
        client = _client(session)

        await client.async_get_consumptions("SUB001")

        assert "/deli/section_subscription/SUB001/consumptions" in session.get.call_args.args[0]

    async def test_weekly_endpoint_params(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(200, {})
        client = _client(session)

        await client.async_get_weekly("SUB001", 2026, 9, 14)

        assert session.get.call_args.kwargs["params"] == {"year": 2026, "month": 9, "day": 14}

    async def test_monthly_endpoint_params(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(200, {})
        client = _client(session)

        await client.async_get_monthly("SUB001", 2026, 9)

        assert session.get.call_args.kwargs["params"] == {"year": 2026, "month": 9}

    async def test_yearly_endpoint_params(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(200, {})
        client = _client(session)

        await client.async_get_yearly("SUB001", 2026)

        assert session.get.call_args.kwargs["params"] == {"year": 2026}
