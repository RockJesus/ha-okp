"""Switch platform for the OKP Cloud vacuum integration (carpet booster)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import OkpApi, OkpApiError
from .const import DOMAIN
from .coordinator import OkpCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    api: OkpApi = hass.data[DOMAIN][entry.entry_id]["api"]
    coordinator: OkpCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    device_id = entry.data.get("third_dev_id") or entry.data.get("device_id")
    name = entry.data.get("device_name") or "OKP 扫地机器人"
    model = entry.data.get("model")
    async_add_entities([OkpCarpetBoosterSwitch(coordinator, api, device_id, name, model)])


class OkpCarpetBoosterSwitch(CoordinatorEntity[OkpCoordinator], SwitchEntity):
    """Carpet booster (carpetBooster dp) on/off control."""

    _attr_has_entity_name = True

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
        self._attr_unique_id = f"{DOMAIN}_{device_id}_carpet_booster"
        self._attr_translation_key = "carpet_booster"
        self._attr_icon = "mdi:layers"
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
        value = params.get("carpetBooster")
        if value is None:
            return None
        return bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, on: bool) -> None:
        try:
            await self.api.set_thing_params(self.device_id, {"carpetBooster": on})
        except OkpApiError as err:
            _LOGGER.warning("OKP set carpet booster failed: %s", err)
            raise
        await self.coordinator.async_request_refresh()
