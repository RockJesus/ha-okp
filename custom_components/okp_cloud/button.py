"""Button platform for the OKP Cloud vacuum integration.

The v3.4.0 app has a "查找机器人" (find the robot) action that writes
``{"call": 1}``; the robot starts beeping so you can locate it under a sofa.
Earlier builds only exposed the raw ``call`` dp as a diagnostic sensor, which
made an action look like a number. It belongs here.
"""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import OkpApi, OkpApiError
from .const import CALL_DP, DOMAIN
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
        entities.append(
            OkpFindRobotButton(
                coordinator,
                api,
                third,
                dev.get("name") or "OKP 扫地机器人",
                dev.get("model"),
            )
        )
    async_add_entities(entities)


class OkpFindRobotButton(CoordinatorEntity[OkpCoordinator], ButtonEntity):
    """Make the robot beep ("查找机器人")."""

    _attr_has_entity_name = True
    _attr_translation_key = "find_robot"
    _attr_icon = "mdi:bullhorn"

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
        self._attr_unique_id = f"{DOMAIN}_{device_id}_find_robot"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=name,
            manufacturer="OKP",
            model=model or "OKP 扫地机器人",
        )

    @property
    def available(self) -> bool:
        """Control is a cloud call; a stale poll must not disable the button."""
        return True

    async def async_press(self) -> None:
        try:
            await self.api.set_thing_params(self.device_id, {CALL_DP: 1})
        except OkpApiError as err:
            _LOGGER.warning("OKP find-robot failed: %s", err)
            raise HomeAssistantError(f"OKP 查找机器人失败：{err}") from err
        self.coordinator.async_schedule_refresh((4.0,))
