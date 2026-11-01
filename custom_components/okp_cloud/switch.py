"""Switch platform for the OKP Cloud vacuum integration.

Two boolean dps are user-facing settings on this model family (the vendor's
device-detail-info "pid_func_configs" table names them explicitly):

* ``carpetBooster`` -> func "carpet_booster_switch"    (地毯增压)
* ``dp31``          -> func "carpet_detection_switch"  (地毯检测, v1.3.0)
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import OkpApi, OkpApiError
from .const import (
    CARPET_DETECTION_DP,
    CARPET_DETECTION_REQUIRES_DP,
    DOMAIN,
    SWITCH_REQUIRES_DP,
)
from .coordinator import OkpCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    api: OkpApi = hass.data[DOMAIN][entry.entry_id]["api"]
    coordinators: dict[str, OkpCoordinator] = hass.data[DOMAIN][entry.entry_id]["coordinators"]
    entities = []
    for dev in entry.data.get("devices", []):
        third = dev.get("third_dev_id")
        coordinator = coordinators.get(third)
        if coordinator is None:
            continue
        # Capability filter: only models exposing the dp get the switch. An
        # empty params dict means "not known yet" - create the entity anyway.
        params = (coordinator.data or {}).get("params") or {}
        common = (
            api,
            third,
            dev.get("name") or "OKP 扫地机器人",
            dev.get("model"),
        )
        if not params or SWITCH_REQUIRES_DP in params:
            entities.append(OkpCarpetBoosterSwitch(coordinator, *common))
        if not params or CARPET_DETECTION_REQUIRES_DP in params:
            entities.append(OkpCarpetDetectionSwitch(coordinator, *common))
    async_add_entities(entities)


class _OkpBoolSwitch(CoordinatorEntity[OkpCoordinator], SwitchEntity):
    """Base for switches backed by a single boolean CoolKit dp."""

    _attr_has_entity_name = True
    _dp_key: str = ""
    _unique_suffix: str = ""
    _icon: str = "mdi:toggle-switch"
    _label: str = "OKP 开关"

    def __init__(
        self,
        coordinator: OkpCoordinator,
        api: OkpApi,
        device_id: str,
        name: str,
        model: str | None,
    ) -> None:
        super().__init__(coordinator)
        self.api = api
        self.device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{self._unique_suffix}"
        self._attr_translation_key = self._unique_suffix
        self._attr_icon = self._icon
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
    def is_on(self) -> bool | None:
        params = self.coordinator.data.get("params", {}) if self.coordinator.data else {}
        value = params.get(self._dp_key)
        if value is None:
            return None
        return bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, on: bool) -> None:
        try:
            await self.api.set_thing_params(self.device_id, {self._dp_key: on})
        except OkpApiError as err:
            _LOGGER.warning("OKP set %s failed: %s", self._dp_key, err)
            raise HomeAssistantError(f"OKP 设置{self._label}失败：{err}") from err
        self.coordinator.async_schedule_refresh()


class OkpCarpetBoosterSwitch(_OkpBoolSwitch):
    """Carpet booster (carpetBooster dp): raise suction on carpets."""

    _dp_key = "carpetBooster"
    _unique_suffix = "carpet_booster"
    _icon = "mdi:layers"
    _label = "地毯增压"


class OkpCarpetDetectionSwitch(_OkpBoolSwitch):
    """Carpet detection (dp31): recognise carpet, clean it without mopping.

    New in v1.3.0. The v3.4.0 app capture shows this dp driven from an ordinary
    on/off setting ("地毯检测" in the app), so exposing it as a diagnostic
    sensor only - what earlier builds did - hid a control the app has.
    """

    _dp_key = CARPET_DETECTION_DP
    _unique_suffix = "carpet_detection"
    _icon = "mdi:rug"
    _label = "地毯检测"
