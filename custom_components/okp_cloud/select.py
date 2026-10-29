"""Select platform for the OKP Cloud vacuum integration (clean mode)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import OkpApi, OkpApiError
from .const import DOMAIN, MODE_LIST, MODE_TO_VALUE, VALUE_TO_MODE
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
    async_add_entities([OkpModeSelect(coordinator, api, device_id, name, model)])


class OkpModeSelect(CoordinatorEntity[OkpCoordinator], SelectEntity):
    """Clean mode selector (smart / random / wall-follow / spiral)."""

    _attr_has_entity_name = True
    _attr_options = MODE_LIST

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
        self._attr_unique_id = f"{DOMAIN}_{device_id}_mode"
        self._attr_translation_key = "clean_mode"
        self._attr_icon = "mdi:map-legend"
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
    def current_option(self) -> str | None:
        params = self.coordinator.data.get("params", {}) if self.coordinator.data else {}
        try:
            value = int(params.get("mode"))
        except (TypeError, ValueError):
            return None
        return VALUE_TO_MODE.get(value, str(value))

    async def async_select_option(self, option: str) -> None:
        value = MODE_TO_VALUE.get(option)
        if value is None:
            raise ValueError(f"unknown clean mode {option}")
        try:
            await self.api.set_thing_params(self.device_id, {"mode": value})
        except OkpApiError as err:
            _LOGGER.warning("OKP set clean mode failed: %s", err)
            raise
        await self.coordinator.async_request_refresh()
