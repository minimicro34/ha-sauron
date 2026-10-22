"""Unit tests for SAURon Lovelace resource registration."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.sauron.frontend import _CARD_PATH, _CARD_URL, async_register_card


class Resources:
    def __init__(self, items=None, loaded=False):
        self.items = list(items or [])
        self.loaded = loaded
        self.async_load = AsyncMock(side_effect=self.load)
        self.async_create_item = AsyncMock(side_effect=self.create)
        self.async_update_item = AsyncMock(side_effect=self.update)

    async def load(self):
        self.loaded = True

    async def create(self, item):
        self.items.append({"id": str(len(self.items) + 1), **item})

    async def update(self, item_id, changes):
        for item in self.items:
            if item["id"] == item_id:
                item.update(changes)

    def async_items(self):
        return list(self.items)


@pytest.fixture
def ha(monkeypatch):
    """Provide minimal HTTP module and Home Assistant registry stubs."""
    http_module = ModuleType("homeassistant.components.http")
    http_module.StaticPathConfig = lambda url, path, cache: (url, path, cache)
    monkeypatch.setitem(sys.modules, "homeassistant.components.http", http_module)
    resources = Resources()
    hass = SimpleNamespace(
        data={"lovelace": SimpleNamespace(resource_mode="storage", resources=resources)},
        http=SimpleNamespace(async_register_static_paths=AsyncMock()),
    )
    return hass, resources


@pytest.mark.asyncio
async def test_register_once_and_repeat(ha):
    hass, resources = ha
    await async_register_card(hass)
    await async_register_card(hass)
    assert hass.http.async_register_static_paths.await_count == 1
    assert resources.async_load.await_count == 1
    assert resources.async_create_item.await_count == 1
    assert resources.items == [{"id": "1", "url": _CARD_URL, "res_type": "module"}]


@pytest.mark.asyncio
async def test_upgrade_resource_url_and_type(ha):
    hass, resources = ha
    resources.items = [{"id": "old", "url": _CARD_PATH + "?v=old", "res_type": "js"}]
    await async_register_card(hass)
    assert resources.async_create_item.await_count == 0
    assert resources.async_update_item.await_count == 1
    assert resources.items[0]["url"] == _CARD_URL
    assert resources.items[0]["res_type"] == "module"


@pytest.mark.asyncio
async def test_existing_resource_unchanged(ha):
    hass, resources = ha
    resources.items = [{"id": "1", "url": _CARD_URL, "res_type": "module"}]
    await async_register_card(hass)
    assert resources.async_update_item.await_count == 0
    assert resources.async_create_item.await_count == 0


@pytest.mark.asyncio
async def test_yaml_mode_registers_static_path_only(ha):
    hass, resources = ha
    hass.data["lovelace"].resource_mode = "yaml"
    await async_register_card(hass)
    assert hass.http.async_register_static_paths.await_count == 1
    assert resources.async_load.await_count == 0
    assert resources.async_create_item.await_count == 0


@pytest.mark.asyncio
async def test_missing_lovelace_registers_static_path_only(ha):
    hass, resources = ha
    del hass.data["lovelace"]
    await async_register_card(hass)
    assert hass.http.async_register_static_paths.await_count == 1
    assert resources.async_load.await_count == 0


@pytest.mark.asyncio
async def test_duplicate_resources_not_added(ha):
    hass, resources = ha
    resources.items = [
        {"id": "a", "url": _CARD_PATH + "?v=old", "res_type": "module"},
        {"id": "b", "url": _CARD_URL, "res_type": "module"},
    ]
    await async_register_card(hass)
    assert resources.async_create_item.await_count == 0
    assert resources.async_update_item.await_count == 1


@pytest.mark.asyncio
async def test_resource_create_failure_can_retry(ha):
    hass, resources = ha
    resources.async_create_item = AsyncMock(side_effect=RuntimeError("storage failure"))
    with pytest.raises(RuntimeError, match="storage failure"):
        await async_register_card(hass)
    resources.async_create_item = AsyncMock(side_effect=resources.create)
    await async_register_card(hass)
    assert resources.async_create_item.await_count == 1
    assert hass.http.async_register_static_paths.await_count == 1
