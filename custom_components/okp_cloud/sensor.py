"""Diagnostic sensors for the OKP Cloud vacuum integration."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VALUE_TO_MODE
from .coordinator import OkpCoordinator


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_mode(params: dict[str, Any]) -> str | None:
    value = _int(params.get("mode"))
    if value is None:
        return None
    return VALUE_TO_MODE.get(value, str(value))


def _str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _timers(params: dict[str, Any]) -> str | None:
    """Summarise CoolKit scheduled cleaning timers."""
    timers = params.get("timers")
    if not isinstance(timers, list):
        return None
    enabled = sum(1 for t in timers if t.get("enabled"))
    return f"{len(timers)} timers, {enabled} enabled"


SENSORS: list[tuple[str, Callable[[dict[str, Any]], Any], str, SensorDeviceClass | None, str | None, bool]] = [
    # (key, value_fn, icon, device_class, unit, entity_category_diagnostic)
    ("work_state", lambda p: p.get("wstate"), "mdi:state-machine", None, None, False),
    ("clean_mode", _clean_mode, "mdi:map-legend", None, None, False),
    ("fault_code", lambda p: _int(p.get("fault")), "mdi:alert-circle-outline", None, None, True),
    ("rssi", lambda p: _int(p.get("rssi")), "mdi:wifi", SensorDeviceClass.SIGNAL_STRENGTH, "dBm", True),
    ("firmware_version", lambda p: _str(p.get("fwVersion")), "mdi:chip", None, None, True),
    ("cleaning_area", lambda p: _str(p.get("cleaningArea")), "mdi:ruler-square", None, None, False),
    ("cleaning_times", lambda p: _int(p.get("cleaningTimes")), "mdi:counter", None, None, False),
    ("carpet_booster", lambda p: p.get("carpetBooster"), "mdi:layers", None, None, True),
    # CoolKit "power" dp carries the battery percentage (0-100).
    ("battery", lambda p: _int(p.get("power")), "mdi:battery", SensorDeviceClass.BATTERY, "%", False),
    # Additional device data points (diagnostic).
    ("dp31", lambda p: p.get("dp31"), "mdi:orbit", None, None, True),
    ("last_clean_start", lambda p: _str(p.get("startUpload")), "mdi:play-clock", None, None, True),
    ("last_clean_end", lambda p: _str(p.get("endUpload")), "mdi:clock-end", None, None, True),
    ("ui_active", lambda p: _int(p.get("uiActive")), "mdi:timer-outline", None, None, True),
    ("call", lambda p: _int(p.get("call")), "mdi:phone-alert", None, None, True),
    ("timers", _timers, "mdi:calendar-clock", None, None, True),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: OkpCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    device_id = entry.data.get("third_dev_id") or entry.data.get("device_id")
    name = entry.data.get("device_name") or "OKP 扫地机器人"
    model = entry.data.get("model")
    entities = [
        OkpSensor(coordinator, device_id, name, model, key, value_fn, icon, device_class, unit, diagnostic)
        for key, value_fn, icon, device_class, unit, diagnostic in SENSORS
    ]
    entities.append(OkpOnlineSensor(coordinator, device_id, name, model))
    async_add_entities(entities)


class OkpSensor(CoordinatorEntity[OkpCoordinator], SensorEntity):
    """A diagnostic sensor backed by the shared coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OkpCoordinator,
        device_id: str,
        name: str,
        model: str | None,
        key: str,
        value_fn: Callable[[dict[str, Any]], Any],
        icon: str | None,
        device_class: SensorDeviceClass | None,
        unit: str | None,
        diagnostic: bool,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._value_fn = value_fn
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{key}"
        self._attr_translation_key = key
        self._attr_icon = icon
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        if diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=name,
            manufacturer="OKP",
            model=model or "OKP 扫地机器人",
        )

    @property
    def available(self) -> bool:
        """Keep last known value during cloud outages."""
        return True

    @property
    def native_value(self) -> Any:
        params = self.coordinator.data.get("params", {}) if self.coordinator.data else {}
        return self._value_fn(params)


class OkpOnlineSensor(CoordinatorEntity[OkpCoordinator], SensorEntity):
    """Online status sensor for the vacuum."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OkpCoordinator,
        device_id: str,
        name: str,
        model: str | None,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_online"
        self._attr_translation_key = "online"
        self._attr_icon = "mdi:cloud-check"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=name,
            manufacturer="OKP",
            model=model or "OKP 扫地机器人",
        )

    @property
    def available(self) -> bool:
        """Keep last known value during cloud outages."""
        return True

    @property
    def native_value(self) -> str:
        online = self.coordinator.data.get("online") if self.coordinator.data else None
        return "online" if online else "offline"
