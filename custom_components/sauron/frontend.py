"""Register bundled SAURon dashboard card without duplicate Lovelace resources."""

import asyncio
import logging
from pathlib import Path
from urllib.parse import urlsplit

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
_CARD_PATH = "/sauron/sauron-card.js"
_CARD_URL = f"{_CARD_PATH}?v=0.7.0b1"
_LOCK_KEY = "sauron_frontend_lock"
_PATH_KEY = "sauron_frontend_path_registered"


async def async_register_card(hass: HomeAssistant) -> None:
    """Expose bundled JavaScript and register a single storage-mode resource."""
    async with hass.data.setdefault(_LOCK_KEY, asyncio.Lock()):
        if not hass.data.get(_PATH_KEY):
            await hass.http.async_register_static_paths(
                [StaticPathConfig(
                    _CARD_PATH,
                    str(Path(__file__).parent / "www" / "sauron-card.js"),
                    False,
                )]
            )
            hass.data[_PATH_KEY] = True

        lovelace = hass.data.get("lovelace")
        if lovelace is None:
            _LOGGER.info("Lovelace unavailable; register %s manually", _CARD_URL)
            return
        if lovelace.resource_mode != "storage":
            _LOGGER.info("Lovelace YAML mode; register %s manually", _CARD_URL)
            return

        resources = lovelace.resources
        if not resources.loaded:
            await resources.async_load()

        matching = [
            item for item in resources.async_items()
            if urlsplit(item["url"]).path == _CARD_PATH
        ]
        if matching:
            for item in matching:
                if item["url"] != _CARD_URL or item.get("res_type") != "module":
                    await resources.async_update_item(
                        item["id"], {"url": _CARD_URL, "res_type": "module"}
                    )
            if len(matching) > 1:
                _LOGGER.warning("Duplicate SAURon card resources detected")
            return

        await resources.async_create_item({"url": _CARD_URL, "res_type": "module"})
        _LOGGER.info("Registered bundled SAURon card: %s", _CARD_URL)
