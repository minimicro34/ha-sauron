"""Async HTTP client for the SAUR API (apib2c.azure.saurclient.fr).

Authentication flow:
  POST /admin/v2/auth  →  { token: { access_token }, clientId, defaultSectionId,
                           expires_in? }

The reCAPTCHA v3 field accepted by the API is a literal string "true",
not a real token — the server-side check is not enforced for non-browser
clients. We replicate the same payload as the official web app.

Token lifecycle (Plan A):
  - Token stored in a TokenCache value object with an absolute expiry.
  - If the SAUR response includes ``expires_in`` we use it; otherwise we
    fall back to DEFAULT_TOKEN_TTL_S.
  - Re-authentication is triggered:
      * lazily when the cache is invalid or near expiry
        (TOKEN_REFRESH_MARGIN_S guard, double-checked under an asyncio.Lock),
      * reactively on 401/403 from any data endpoint (one retry).
  - On the retry path we distinguish *transient* failures (network /
    5xx from the auth endpoint itself) from *real* auth failures.
    Only the latter raise SauronAuthError → ConfigEntryAuthFailed.
  - The optional ``on_token_refreshed`` callback lets the HA layer
    persist the cache to ``entry.data`` so it survives restarts.

Field names are sourced from reverse-engineering the eyeonsaur-ha integration
and the Saur_fr_client library (https://github.com/cekage/Saur_fr_client).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import aiohttp

from ..const import DEFAULT_TOKEN_TTL_S, TOKEN_REFRESH_MARGIN_S
from .exceptions import (
    SauronApiError,
    SauronAuthError,
    SauronNoDataError,
    SauronTransientError,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

_LOGGER = logging.getLogger(__name__)

_BASE_URL = "https://apib2c.azure.saurclient.fr"
_AUTH_ENDPOINT = "/admin/v2/auth"
_WEBSITE_AREAS_ENDPOINT = "/admin/users/v2/website_areas/{client_id}"
_DELIVERY_POINTS_ENDPOINT = "/deli/section_subscriptions/{section_id}/supply_areas/delivery_points"
_METER_INDEXES_ENDPOINT = "/deli/section_subscriptions/{section_id}/meter_indexes/last"
_CONSUMPTIONS_ENDPOINT = "/deli/section_subscription/{section_id}/consumptions"
_CONSUMPTIONS_WEEKLY_ENDPOINT = "/deli/section_subscription/{section_id}/consumptions/weekly"
_CONSUMPTIONS_MONTHLY_ENDPOINT = "/deli/section_subscription/{section_id}/consumptions/monthly"
_CONSUMPTIONS_YEARLY_ENDPOINT = "/deli/section_subscription/{section_id}/consumptions/yearly"


@dataclass(frozen=True, slots=True)
class TokenCache:
    """Bearer token + identifiers + absolute expiry.

    Stored in memory and (optionally) persisted to ``entry.data`` so it
    survives Home Assistant restarts.  ``expires_at`` is epoch seconds.
    """

    access_token: str
    expires_at: float
    client_id: str
    default_section_id: str


class SauronApiClient:
    """Async SAUR API client — one instance per config entry."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        login: str,
        password: str,
        *,
        initial_token: TokenCache | None = None,
        on_token_refreshed: Callable[[TokenCache], Awaitable[None]] | None = None,
    ) -> None:
        self._session = session
        self._login = login
        self._password = password
        self._cache: TokenCache | None = initial_token
        self._on_token_refreshed = on_token_refreshed
        self._auth_lock: asyncio.Lock = asyncio.Lock()

    # ── Authentication ────────────────────────────────────────────────────────

    async def async_authenticate(self) -> None:
        """Obtain a fresh Bearer token and discover client_id.

        Raises SauronAuthError on invalid credentials.
        Raises SauronApiError on unexpected HTTP errors.

        Response structure:
          { "token": { "access_token": "..." }, "clientId": "...",
            "defaultSectionId": "...", "expires_in"?: int }
        """
        payload = {
            "username": self._login,
            "password": self._password,
            "client_id": "frontjs-client",
            "grant_type": "password",
            "scope": "api-scope",
            "isRecaptchaV3": True,
            "captchaToken": "true",
        }
        async with self._session.post(
            f"{_BASE_URL}{_AUTH_ENDPOINT}", json=payload
        ) as resp:
            if resp.status in (401, 403):
                raise SauronAuthError("Invalid SAUR credentials")
            if resp.status != 200:
                raise SauronApiError(resp.status, await resp.text())
            data: dict[str, Any] = await resp.json()

        token_obj = data.get("token") or {}
        access_token = token_obj.get("access_token") if isinstance(token_obj, dict) else None
        if not access_token:
            raise SauronAuthError("No access_token in auth response")

        raw_ttl = data.get("expires_in")
        try:
            ttl_s = int(raw_ttl) if raw_ttl is not None else DEFAULT_TOKEN_TTL_S
        except (TypeError, ValueError):
            ttl_s = DEFAULT_TOKEN_TTL_S

        self._cache = TokenCache(
            access_token=str(access_token),
            expires_at=time.time() + ttl_s,
            client_id=str(data.get("clientId", "")),
            default_section_id=str(data.get("defaultSectionId", "")),
        )

        _LOGGER.debug(
            "SAUR auth response keys=%s expires_in=%s",
            list(data.keys()),
            raw_ttl,
        )
        _LOGGER.debug(
            "SAUR authenticated: client_id=%s, default_section_id=%s, ttl_s=%d",
            self._cache.client_id,
            self._cache.default_section_id,
            ttl_s,
        )

        if self._on_token_refreshed is not None:
            await self._on_token_refreshed(self._cache)

    @property
    def client_id(self) -> str | None:
        return self._cache.client_id if self._cache else None

    @property
    def default_section_id(self) -> str | None:
        return self._cache.default_section_id if self._cache else None

    def _is_token_valid(self) -> bool:
        """Return True iff we have a non-expired cached token (with margin)."""
        return (
            self._cache is not None
            and time.time() < self._cache.expires_at - TOKEN_REFRESH_MARGIN_S
        )

    async def _ensure_token(self) -> str:
        """Return a valid bearer token, authenticating if necessary.

        Uses a double-checked pattern under self._auth_lock so two concurrent
        callers cannot trigger two POST /auth calls.  The fast path (valid
        cached token) does NOT take the lock.
        """
        if self._is_token_valid():
            assert self._cache is not None
            return self._cache.access_token

        async with self._auth_lock:
            if self._is_token_valid():
                assert self._cache is not None
                return self._cache.access_token
            await self.async_authenticate()

        assert self._cache is not None
        return self._cache.access_token

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET with automatic token refresh on 401/403."""
        token = await self._ensure_token()
        status, body = await self._do_get(path, token, params)

        if status not in (401, 403):
            return body

        _LOGGER.debug("Token rejected (%d) on %s — refreshing", status, path)
        self._cache = None
        try:
            await self.async_authenticate()
        except SauronAuthError:
            raise
        except SauronApiError as err:
            raise SauronTransientError(f"Auth refresh failed: {err}") from err

        assert self._cache is not None
        status2, body2 = await self._do_get(path, self._cache.access_token, params)
        if status2 in (401, 403):
            raise SauronAuthError(f"Endpoint {path} rejected fresh token")
        return body2

    async def _do_get(
        self, path: str, token: str, params: dict[str, Any] | None
    ) -> tuple[int, Any]:
        """Issue a single GET and return (status, body)."""
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with self._session.get(
                f"{_BASE_URL}{path}", headers=headers, params=params
            ) as resp:
                if resp.status in (401, 403):
                    return resp.status, None
                if resp.status != 200:
                    raise SauronApiError(resp.status, await resp.text())
                return resp.status, await resp.json()
        except (TimeoutError, aiohttp.ClientError) as err:
            raise SauronTransientError(f"Network error on {path}: {err}") from err

    async def async_get_website_areas(self, client_id: str) -> dict[str, Any]:
        path = _WEBSITE_AREAS_ENDPOINT.format(client_id=client_id)
        return await self._get(path)

    async def async_get_delivery_points(self, section_id: str) -> dict[str, Any]:
        path = _DELIVERY_POINTS_ENDPOINT.format(section_id=section_id)
        data = await self._get(path)
        if not isinstance(data, dict):
            raise SauronNoDataError(f"Expected dict from delivery_points, got {type(data)}")
        return data

    async def async_get_meter_last_index(self, section_id: str) -> dict[str, Any]:
        path = _METER_INDEXES_ENDPOINT.format(section_id=section_id)
        return await self._get(path)

    async def async_get_consumptions(self, section_id: str) -> dict[str, Any]:
        path = _CONSUMPTIONS_ENDPOINT.format(section_id=section_id)
        return await self._get(path)

    async def async_get_weekly(
        self, section_id: str, year: int, month: int, day: int
    ) -> dict[str, Any]:
        path = _CONSUMPTIONS_WEEKLY_ENDPOINT.format(section_id=section_id)
        return await self._get(path, params={"year": year, "month": month, "day": day})

    async def async_get_monthly(
        self, section_id: str, year: int, month: int
    ) -> dict[str, Any]:
        path = _CONSUMPTIONS_MONTHLY_ENDPOINT.format(section_id=section_id)
        return await self._get(path, params={"year": year, "month": month})

    async def async_get_yearly(self, section_id: str, year: int) -> dict[str, Any]:
        path = _CONSUMPTIONS_YEARLY_ENDPOINT.format(section_id=section_id)
        return await self._get(path, params={"year": year})
