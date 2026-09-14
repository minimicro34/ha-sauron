"""Token persistence + reload-guard tests (Plan A v2 §4.2 — RC-1).

Verifies the hydration/persistence/reload-guard contract of
``custom_components.sauron.__init__`` using lightweight fakes from
``tests/conftest.py``.  No pytest-homeassistant-custom-component
dependency.

Most of these tests focus on the pure functions
``_hydrate_token_from_entry`` and ``_async_update_listener`` because
``async_setup_entry`` pulls in entity-platform forwarding that our
stubs don't model.  The integration-level contract (callback wiring)
is sanity-checked via the persistence callback itself.
"""

from __future__ import annotations

import time
from typing import Any

# Import the integration module under test — using its package name
# so the relative imports resolve against the stubbed homeassistant.
import custom_components.sauron as integration
from custom_components.sauron.api import TokenCache
from custom_components.sauron.const import (
    CONF_TOKEN_CACHE,
    DOMAIN,
    HASS_DATA_OPTIONS_SNAPSHOT,
    TOKEN_REFRESH_MARGIN_S,
)

# ─── _hydrate_token_from_entry ───────────────────────────────────────────────


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
        # Within margin → effectively expired for our purposes
        fake_entry.data[CONF_TOKEN_CACHE] = _valid_cache_dict(expires_in=TOKEN_REFRESH_MARGIN_S - 1)
        assert integration._hydrate_token_from_entry(fake_entry) is None

    def test_returns_none_when_cache_malformed_string(self, fake_entry: Any) -> None:
        fake_entry.data[CONF_TOKEN_CACHE] = "not a dict"
        assert integration._hydrate_token_from_entry(fake_entry) is None

    def test_returns_none_when_cache_missing_keys(self, fake_entry: Any) -> None:
        fake_entry.data[CONF_TOKEN_CACHE] = {"access_token": "x"}  # incomplete
        assert integration._hydrate_token_from_entry(fake_entry) is None

    def test_returns_none_when_cache_bad_types(self, fake_entry: Any) -> None:
        fake_entry.data[CONF_TOKEN_CACHE] = {
            "access_token": "x",
            "expires_at": "not a float",
            "client_id": "c",
            "default_section_id": "s",
        }
        assert integration._hydrate_token_from_entry(fake_entry) is None


# ─── _async_update_listener (RC-1: reload guard) ─────────────────────────────


class TestUpdateListenerReloadGuard:
    async def test_data_only_update_does_not_reload(self, fake_hass: Any, fake_entry: Any) -> None:
        # Setup the options snapshot the way async_setup_entry would.
        fake_hass.data[DOMAIN] = {
            f"{fake_entry.entry_id}_{HASS_DATA_OPTIONS_SNAPSHOT}": dict(fake_entry.options),
        }

        # Mutate entry.data only — options stay identical.
        fake_entry.data = {**fake_entry.data, CONF_TOKEN_CACHE: _valid_cache_dict()}

        await integration._async_update_listener(fake_hass, fake_entry)

        assert fake_hass.config_entries.reload_calls == []

    async def test_options_change_triggers_reload(self, fake_hass: Any, fake_entry: Any) -> None:
        fake_hass.data[DOMAIN] = {
            f"{fake_entry.entry_id}_{HASS_DATA_OPTIONS_SNAPSHOT}": dict(fake_entry.options),
        }

        # Mutate options.
        fake_entry.options = {"scan_interval_h": 12}

        await integration._async_update_listener(fake_hass, fake_entry)

        assert fake_hass.config_entries.reload_calls == [fake_entry.entry_id]

    async def test_listener_updates_snapshot_after_reload(
        self, fake_hass: Any, fake_entry: Any
    ) -> None:
        """Second call with the same new options must NOT reload again."""
        fake_hass.data[DOMAIN] = {
            f"{fake_entry.entry_id}_{HASS_DATA_OPTIONS_SNAPSHOT}": dict(fake_entry.options),
        }
        fake_entry.options = {"scan_interval_h": 12}

        await integration._async_update_listener(fake_hass, fake_entry)
        await integration._async_update_listener(fake_hass, fake_entry)

        # Reload fired once on the first change; the snapshot was updated;
        # the second call sees no diff and skips reload.
        assert fake_hass.config_entries.reload_calls == [fake_entry.entry_id]


# ─── Persistence callback (integration with FakeConfigEntries) ───────────────


class TestPersistTokenCallback:
    async def test_persist_writes_back_and_does_not_reload(
        self, fake_hass: Any, fake_entry: Any
    ) -> None:
        """RC-1 end-to-end: the callback used in async_setup_entry writes
        the token to entry.data, the update listener fires, and reload is
        NOT called because options didn't change.
        """
        # Mirror what async_setup_entry does for the listener + snapshot.
        fake_hass.data[DOMAIN] = {
            f"{fake_entry.entry_id}_{HASS_DATA_OPTIONS_SNAPSHOT}": dict(fake_entry.options),
        }
        fake_entry.add_update_listener(
            lambda hass, entry: integration._async_update_listener(hass, entry)
        )

        # Replicate the callback that async_setup_entry creates.
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

        # Token was written back
        assert fake_entry.data[CONF_TOKEN_CACHE]["access_token"] == "freshly_minted"
        # And NO reload was triggered (RC-1 guard worked)
        assert fake_hass.config_entries.reload_calls == []
