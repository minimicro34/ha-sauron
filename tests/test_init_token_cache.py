"""Token persistence, setup lifecycle and reload-guard tests."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import custom_components.sauron as integration
from custom_components.sauron.api import TokenCache
from custom_components.sauron.const import (
    CONF_TOKEN_CACHE,
    DOMAIN,
    HASS_DATA_OPTIONS_SNAPSHOT,
    TOKEN_REFRESH_MARGIN_S,
)


def _valid_cache_dict(*, expires_in: int = 3600) -> dict[str, Any]:
    return {
        "access_token": "tok_persisted",
        "expires_at": time.time() + expires_in,
        "client_id": "CLI001",
        "default_section_id": "SUB001",
    }


class TestHydrateTokenFromEntry:
    def test_hydrates_from_valid_cache(self, fake_entry: Any) -> None:
        fake_entry.data[CONF_TOKEN_CACHE] = _valid_cache_dict()

        cache = integration._hydrate_token_from_entry(fake_entry)

        assert isinstance(cache, TokenCache)
        assert cache.access_token == "tok_persisted"
        assert cache.client_id == "CLI001"

    def test_returns_none_when_cache_missing(self, fake_entry: Any) -> None:
        assert CONF_TOKEN_CACHE not in fake_entry.data
        assert integration._hydrate_token_from_entry(fake_entry) is None

    def test_returns_none_when_cache_expired(self, fake_entry: Any) -> None:
        fake_entry.data[CONF_TOKEN_CACHE] = _valid_cache_dict(expires_in=-10)
        assert integration._hydrate_token_from_entry(fake_entry) is None

    def test_returns_none_when_cache_within_refresh_margin(self, fake_entry: Any) -> None:
        fake_entry.data[CONF_TOKEN_CACHE] = _valid_cache_dict(expires_in=TOKEN_REFRESH_MARGIN_S - 1)
        assert integration._hydrate_token_from_entry(fake_entry) is None

    def test_returns_none_when_cache_malformed_string(self, fake_entry: Any) -> None:
        fake_entry.data[CONF_TOKEN_CACHE] = "not a dict"
        assert integration._hydrate_token_from_entry(fake_entry) is None

    def test_returns_none_when_cache_missing_keys(self, fake_entry: Any) -> None:
        fake_entry.data[CONF_TOKEN_CACHE] = {"access_token": "x"}
        assert integration._hydrate_token_from_entry(fake_entry) is None

    def test_returns_none_when_cache_bad_types(self, fake_entry: Any) -> None:
        fake_entry.data[CONF_TOKEN_CACHE] = {
            "access_token": "x",
            "expires_at": "not a float",
            "client_id": "c",
            "default_section_id": "s",
        }
        assert integration._hydrate_token_from_entry(fake_entry) is None


class TestUpdateListenerReloadGuard:
    async def test_data_only_update_does_not_reload(self, fake_hass: Any, fake_entry: Any) -> None:
        fake_hass.data[DOMAIN] = {
            f"{fake_entry.entry_id}_{HASS_DATA_OPTIONS_SNAPSHOT}": dict(fake_entry.options),
        }
        fake_entry.data = {**fake_entry.data, CONF_TOKEN_CACHE: _valid_cache_dict()}

        await integration._async_update_listener(fake_hass, fake_entry)

        assert fake_hass.config_entries.reload_calls == []

    async def test_options_change_triggers_reload(self, fake_hass: Any, fake_entry: Any) -> None:
        fake_hass.data[DOMAIN] = {
            f"{fake_entry.entry_id}_{HASS_DATA_OPTIONS_SNAPSHOT}": dict(fake_entry.options),
        }
        fake_entry.options = {"scan_interval_h": 12}

        await integration._async_update_listener(fake_hass, fake_entry)

        assert fake_hass.config_entries.reload_calls == [fake_entry.entry_id]

    async def test_listener_updates_snapshot_after_reload(
        self, fake_hass: Any, fake_entry: Any
    ) -> None:
        fake_hass.data[DOMAIN] = {
            f"{fake_entry.entry_id}_{HASS_DATA_OPTIONS_SNAPSHOT}": dict(fake_entry.options),
        }
        fake_entry.options = {"scan_interval_h": 12}

        await integration._async_update_listener(fake_hass, fake_entry)
        await integration._async_update_listener(fake_hass, fake_entry)

        assert fake_hass.config_entries.reload_calls == [fake_entry.entry_id]

    async def test_listener_without_existing_domain_snapshot_reloads(
        self, fake_hass: Any, fake_entry: Any
    ) -> None:
        fake_entry.options = {"scan_interval_h": 8}

        await integration._async_update_listener(fake_hass, fake_entry)

        assert fake_hass.config_entries.reload_calls == [fake_entry.entry_id]


class TestPersistTokenCallback:
    async def test_persist_writes_back_and_does_not_reload(
        self, fake_hass: Any, fake_entry: Any
    ) -> None:
        fake_hass.data[DOMAIN] = {
            f"{fake_entry.entry_id}_{HASS_DATA_OPTIONS_SNAPSHOT}": dict(fake_entry.options),
        }
        fake_entry.add_update_listener(
            lambda hass, entry: integration._async_update_listener(hass, entry)
        )

        from dataclasses import asdict

        async def _persist_token(cache: TokenCache) -> None:
            new_data = {**fake_entry.data, CONF_TOKEN_CACHE: asdict(cache)}
            fake_hass.config_entries.async_update_entry(fake_entry, data=new_data)

        cache = TokenCache(
            access_token="freshly_minted",
            expires_at=time.time() + 3600,
            client_id="CLI001",
            default_section_id="SUB001",
        )
        await _persist_token(cache)
        await fake_hass._drain_update_listeners()

        assert fake_entry.data[CONF_TOKEN_CACHE]["access_token"] == "freshly_minted"
        assert fake_hass.config_entries.reload_calls == []


class TestIntegrationLifecycle:
    async def test_setup_entry_wires_client_coordinator_and_platforms(
        self, monkeypatch: Any, fake_hass: Any, fake_entry: Any
    ) -> None:
        fake_entry.options = {"scan_interval_h": 6}
        fake_entry.data[CONF_TOKEN_CACHE] = _valid_cache_dict()
        session = object()
        monkeypatch.setattr(integration, "async_get_clientsession", lambda hass: session)

        client = MagicMock()
        client_factory = MagicMock(return_value=client)
        monkeypatch.setattr(integration, "SauronApiClient", client_factory)

        coordinator = MagicMock()
        coordinator.async_setup = AsyncMock()
        coordinator.async_config_entry_first_refresh = AsyncMock()
        coordinator_factory = MagicMock(return_value=coordinator)
        monkeypatch.setattr(integration, "SauronCoordinator", coordinator_factory)

        assert await integration.async_setup_entry(fake_hass, fake_entry) is True

        client_factory.assert_called_once()
        kwargs = client_factory.call_args.kwargs
        assert kwargs["session"] is session
        assert kwargs["initial_token"].access_token == "tok_persisted"
        coordinator_factory.assert_called_once_with(fake_hass, client, fake_entry)
        coordinator.async_setup.assert_awaited_once()
        coordinator.async_config_entry_first_refresh.assert_awaited_once()
        assert fake_hass.data[DOMAIN][fake_entry.entry_id] is coordinator
        snapshot_key = f"{fake_entry.entry_id}_{HASS_DATA_OPTIONS_SNAPSHOT}"
        assert fake_hass.data[DOMAIN][snapshot_key] == {"scan_interval_h": 6}
        assert fake_hass.config_entries.forward_calls == [
            (fake_entry.entry_id, tuple(integration.PLATFORMS))
        ]
        assert len(fake_entry._update_listeners) == 1
        assert len(fake_entry._unload_callbacks) == 1

    async def test_setup_persist_callback_updates_entry_data(
        self, monkeypatch: Any, fake_hass: Any, fake_entry: Any
    ) -> None:
        monkeypatch.setattr(integration, "async_get_clientsession", lambda hass: object())
        captured: dict[str, Any] = {}

        def client_factory(**kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock()

        monkeypatch.setattr(integration, "SauronApiClient", client_factory)
        coordinator = MagicMock()
        coordinator.async_setup = AsyncMock()
        coordinator.async_config_entry_first_refresh = AsyncMock()
        monkeypatch.setattr(integration, "SauronCoordinator", MagicMock(return_value=coordinator))

        await integration.async_setup_entry(fake_hass, fake_entry)
        callback = captured["on_token_refreshed"]
        await callback(
            TokenCache(
                access_token="new-token",
                expires_at=time.time() + 3600,
                client_id="CLI002",
                default_section_id="SUB002",
            )
        )
        await fake_hass._drain_update_listeners()

        assert fake_entry.data[CONF_TOKEN_CACHE]["access_token"] == "new-token"
        assert fake_hass.config_entries.reload_calls == []

    async def test_unload_success_removes_coordinator_and_snapshot(
        self, fake_hass: Any, fake_entry: Any
    ) -> None:
        snapshot_key = f"{fake_entry.entry_id}_{HASS_DATA_OPTIONS_SNAPSHOT}"
        fake_hass.data[DOMAIN] = {
            fake_entry.entry_id: object(),
            snapshot_key: {"scan_interval_h": 4},
        }

        assert await integration.async_unload_entry(fake_hass, fake_entry) is True

        assert fake_entry.entry_id not in fake_hass.data[DOMAIN]
        assert snapshot_key not in fake_hass.data[DOMAIN]
        assert fake_hass.config_entries.unload_calls == [
            (fake_entry.entry_id, tuple(integration.PLATFORMS))
        ]

    async def test_unload_failure_keeps_domain_data(self, fake_hass: Any, fake_entry: Any) -> None:
        fake_hass.config_entries.unload_result = False
        fake_hass.data[DOMAIN] = {fake_entry.entry_id: "coordinator"}

        assert await integration.async_unload_entry(fake_hass, fake_entry) is False
        assert fake_hass.data[DOMAIN][fake_entry.entry_id] == "coordinator"

    async def test_migrate_entry_is_noop_success(self, fake_hass: Any, fake_entry: Any) -> None:
        assert await integration.async_migrate_entry(fake_hass, fake_entry) is True
