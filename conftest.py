"""Root conftest — makes custom_components importable without triggering HA imports.

Pure-library tests (test_client, test_models) import from
custom_components.sauron.api.* directly. Python would normally resolve
custom_components/sauron/__init__.py first, which imports homeassistant.
We prevent this by inserting the project root into sys.path so that the
`custom_components` package is resolvable, then monkey-patching a lightweight
stub for `homeassistant` before any integration module is loaded.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

# Ensure project root is on sys.path
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _stub_module(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


# Stub out homeassistant and all sub-modules that our integration package
# imports at module level, so pure-library tests can import api.* without
# requiring a real HA install.
for _name in [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.issue_registry",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.components",
    "homeassistant.components.sensor",
]:
    if _name not in sys.modules:
        _stub_module(_name)

# Minimal stubs needed so that module-level class bodies don't crash
_ha = sys.modules["homeassistant"]

_config_entries = sys.modules["homeassistant.config_entries"]
_config_entries.ConfigEntry = object  # type: ignore[attr-defined]
_config_entries.ConfigFlow = object  # type: ignore[attr-defined]
_config_entries.ConfigFlowResult = object  # type: ignore[attr-defined]
_config_entries.OptionsFlow = object  # type: ignore[attr-defined]
_const = sys.modules["homeassistant.const"]


class _Platform:
    SENSOR = "sensor"


_const.Platform = _Platform  # type: ignore[attr-defined]
_const.EntityCategory = object  # type: ignore[attr-defined]
_const.UnitOfVolume = object  # type: ignore[attr-defined]

_core = sys.modules["homeassistant.core"]
_core.HomeAssistant = object  # type: ignore[attr-defined]
_core.callback = lambda f: f  # type: ignore[attr-defined]

_exc = sys.modules["homeassistant.exceptions"]
_exc.ConfigEntryAuthFailed = Exception  # type: ignore[attr-defined]

_dreg = sys.modules["homeassistant.helpers.device_registry"]
_dreg.DeviceInfo = dict  # type: ignore[attr-defined]

_ireg = sys.modules["homeassistant.helpers.issue_registry"]


class _IssueSeverity:
    WARNING = "warning"
    ERROR = "error"


_ireg.IssueSeverity = _IssueSeverity  # type: ignore[attr-defined]
_ireg.async_create_issue = lambda *a, **kw: None  # type: ignore[attr-defined]
_ireg.async_delete_issue = lambda *a, **kw: None  # type: ignore[attr-defined]

_aiohttp_client = sys.modules["homeassistant.helpers.aiohttp_client"]
_aiohttp_client.async_get_clientsession = lambda hass: None  # type: ignore[attr-defined]

_coord = sys.modules["homeassistant.helpers.update_coordinator"]


class _GenericCoordinator:
    def __init__(self, *args: object, **kwargs: object) -> None:
        # Accept any arguments — real DataUpdateCoordinator signature is
        # large and evolves across HA versions; tests do not exercise it.
        # Capture hass for completeness so subclasses can read self.hass.
        self.hass = args[0] if args else None

    def __class_getitem__(cls, item: object) -> type:
        return cls


_coord.DataUpdateCoordinator = _GenericCoordinator  # type: ignore[attr-defined]
_coord.UpdateFailed = Exception  # type: ignore[attr-defined]
_coord.CoordinatorEntity = object  # type: ignore[attr-defined]

_sensor = sys.modules["homeassistant.components.sensor"]
_sensor.SensorDeviceClass = object  # type: ignore[attr-defined]
_sensor.SensorEntity = object  # type: ignore[attr-defined]
_sensor.SensorEntityDescription = dict  # type: ignore[attr-defined]
_sensor.SensorStateClass = object  # type: ignore[attr-defined]
