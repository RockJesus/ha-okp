"""Shared test scaffolding.

The integration modules import Home Assistant at module level, but the pure
functions under test do not need a running HA - a few lightweight stand-ins are
enough. This keeps the test suite fast and dependency-light (pytest + aiohttp +
voluptuous, no full Home Assistant install).

The stubs are installed *before* any integration import, so they must live in
conftest.py (pytest imports it first).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _install_homeassistant_stubs() -> None:
    """Minimal stand-ins for the homeassistant modules the code imports."""
    if "homeassistant" in sys.modules:
        return

    ha = types.ModuleType("homeassistant")
    sys.modules["homeassistant"] = ha

    const = types.ModuleType("homeassistant.const")
    const.Platform = types.SimpleNamespace(
        VACUUM="vacuum",
        SENSOR="sensor",
        CAMERA="camera",
        SELECT="select",
        SWITCH="switch",
        BUTTON="button",
    )
    const.CONF_PASSWORD = "password"
    const.CONF_ACCOUNT = "account"
    sys.modules["homeassistant.const"] = const

    config_entries = types.ModuleType("homeassistant.config_entries")

    class ConfigFlow:  # noqa: D401 - stand-in base class
        def __init_subclass__(cls, **kwargs):  # pragma: no cover
            kwargs.pop("domain", None)
            super().__init_subclass__(**kwargs)

    class OptionsFlow:  # noqa: D401
        pass

    class ConfigEntryState:  # enum stand-in; only identity is ever compared
        LOADED = "loaded"

    config_entries.ConfigEntry = type("ConfigEntry", (), {})
    config_entries.ConfigFlow = ConfigFlow
    config_entries.OptionsFlow = OptionsFlow
    config_entries.ConfigFlowResult = dict
    config_entries.ConfigEntryState = ConfigEntryState
    sys.modules["homeassistant.config_entries"] = config_entries

    core = types.ModuleType("homeassistant.core")
    core.callback = lambda f: f
    core.HomeAssistant = type("HomeAssistant", (), {})
    core.ServiceCall = type("ServiceCall", (), {})
    core.SupportsResponse = types.SimpleNamespace(ONLY="only", OPTIONAL="optional")
    sys.modules["homeassistant.core"] = core

    helpers = types.ModuleType("homeassistant.helpers")
    sys.modules["homeassistant.helpers"] = helpers

    cv = types.ModuleType("homeassistant.helpers.config_validation")
    cv.string = str
    cv.boolean = bool
    helpers.config_validation = cv
    sys.modules["homeassistant.helpers.config_validation"] = cv

    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda *a, **k: None
    aiohttp_client.async_create_clientsession = lambda *a, **k: None
    helpers.aiohttp_client = aiohttp_client
    sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client

    device_registry = types.ModuleType("homeassistant.helpers.device_registry")
    device_registry.DeviceInfo = dict
    helpers.device_registry = device_registry
    sys.modules["homeassistant.helpers.device_registry"] = device_registry

    entity = types.ModuleType("homeassistant.helpers.entity")
    entity.EntityCategory = types.SimpleNamespace(
        CONFIG="config", DIAGNOSTIC="diagnostic"
    )
    helpers.entity = entity
    sys.modules["homeassistant.helpers.entity"] = entity

    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    entity_platform.AddEntitiesCallback = object
    helpers.entity_platform = entity_platform
    sys.modules["homeassistant.helpers.entity_platform"] = entity_platform

    restore_state = types.ModuleType("homeassistant.helpers.restore_state")

    class RestoreEntity:  # noqa: D401
        pass

    restore_state.RestoreEntity = RestoreEntity
    helpers.restore_state = restore_state
    sys.modules["homeassistant.helpers.restore_state"] = restore_state

    update_coordinator = types.ModuleType(
        "homeassistant.helpers.update_coordinator"
    )

    class DataUpdateCoordinator(dict):  # supports [T] subscription
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, *args, **kwargs):
            self.hass = kwargs.get("hass")

    class CoordinatorEntity:  # noqa: D401
        def __init__(self, coordinator):
            self.coordinator = coordinator

    class UpdateFailed(Exception):
        pass

    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.CoordinatorEntity = CoordinatorEntity
    update_coordinator.UpdateFailed = UpdateFailed
    helpers.update_coordinator = update_coordinator
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator

    exceptions = types.ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        pass

    exceptions.HomeAssistantError = HomeAssistantError
    sys.modules["homeassistant.exceptions"] = exceptions

    components = types.ModuleType("homeassistant.components")
    sys.modules["homeassistant.components"] = components

    for name, attrs in (
        ("button", {"ButtonEntity": type("ButtonEntity", (), {})}),
        ("camera", {"Camera": type("Camera", (), {})}),
        ("select", {"SelectEntity": type("SelectEntity", (), {})}),
        (
            "sensor",
            {
                "SensorEntity": type("SensorEntity", (), {}),
                "SensorDeviceClass": types.SimpleNamespace(
                    BATTERY="battery", TIMESTAMP="timestamp"
                ),
            },
        ),
        ("switch", {"SwitchEntity": type("SwitchEntity", (), {})}),
        (
            "vacuum",
            {
                "StateVacuumEntity": type("StateVacuumEntity", (), {}),
                "VacuumEntityFeature": types.SimpleNamespace(
                    RETURN_HOME=1, SEND_COMMAND=2, FAN_SPEED=4, LOCATE=8
                ),
            },
        ),
    ):
        mod = types.ModuleType(f"homeassistant.components.{name}")
        for attr, value in attrs.items():
            setattr(mod, attr, value)
        setattr(components, name, mod)
        sys.modules[f"homeassistant.components.{name}"] = mod


_install_homeassistant_stubs()


@pytest.fixture
def config_entry_factory():
    """Build stand-in ConfigEntry objects (only what entity_scope reads)."""
    from datetime import datetime, timezone

    def _make(entry_id: str, created_at: float | None) -> object:
        class Entry:
            domain = "okp_cloud"

            def __init__(self):
                self.entry_id = entry_id
                if created_at is None:
                    # Simulate the pre-2022.7 shape: no attribute at all.
                    pass
                else:
                    self.created_at = datetime.fromtimestamp(
                        created_at, tz=timezone.utc
                    )

        return Entry()

    return _make


@pytest.fixture
def hass_with_entries(config_entry_factory):
    """A stand-in hass exposing hass.config_entries.async_entries()."""

    class ConfigEntries:
        def __init__(self, entries):
            self._entries = entries

        def async_entries(self, domain):
            return [e for e in self._entries if e.domain == domain]

    class Hass:
        def __init__(self, entries):
            self.config_entries = ConfigEntries(entries)

    def _make(ids_and_dates: list[tuple[str, float | None]]):
        entries = [config_entry_factory(i, ts) for i, ts in ids_and_dates]
        return Hass(entries), entries

    return _make
