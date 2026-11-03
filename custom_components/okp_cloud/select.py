"""Select platform for the OKP Cloud vacuum integration (clean mode)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import OkpApi, OkpApiError
from .const import (
    DOMAIN,
    MODE_LABEL_LIST,
    MODE_LABEL_TO_VALUE,
    MODE_TO_VALUE,
    SELECT_REQUIRES_DP,
    VALUE_TO_MODE_LABEL,
    entity_scope,
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
    scope = entity_scope(hass, entry)
    for dev in entry.data.get("devices", []):
        third = dev.get("third_dev_id")
        coordinator = coordinators.get(third)
        if coordinator is None:
            continue
        # Capability filter: only models exposing the mode dp get a selector.
        params = (coordinator.data or {}).get("params") or {}
        if params.keys() and SELECT_REQUIRES_DP not in params:
            continue
        entities.append(
            OkpModeSelect(
                coordinator,
                api,
                third,
                dev.get("name") or "OKP 扫地机器人",
                dev.get("model"),
                scope=scope,
            )
        )
    async_add_entities(entities)


class OkpModeSelect(CoordinatorEntity[OkpCoordinator], SelectEntity, RestoreEntity):
    """Clean mode selector, labelled in Chinese (智能 / 随机 / 沿边 / 螺旋)."""

    _attr_has_entity_name = True
    _attr_options = MODE_LABEL_LIST

    def __init__(
        self,
        coordinator: OkpCoordinator,
        api: OkpApi,
        device_id: str,
        name: str,
        model: str | None,
        scope: str = "",
    ) -> None:
        super().__init__(coordinator)
        self.api = api
        self.device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}_mode{scope}"
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

    async def async_added_to_hass(self) -> None:
        """Carry the pre-relabel state over to its Chinese label.

        Until the first successful poll, Home Assistant restores the state
        this entity had before v1.4.10 - the English code ("smart"). That
        value is no longer one of the options, so the selector would sit at
        an unknown value for up to one poll interval after an upgrade.
        Translate it on the way in.
        """
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in MODE_TO_VALUE:
            self._attr_state = VALUE_TO_MODE_LABEL[MODE_TO_VALUE[last.state]]

    @property
    def current_option(self) -> str | None:
        params = self.coordinator.data.get("params", {}) if self.coordinator.data else {}
        try:
            value = int(params.get("mode"))
        except (TypeError, ValueError):
            # No dp yet (first poll still pending): fall back to the restored
            # label so the selector does not flash an unknown state.
            return self._attr_state if self._attr_state in self._attr_options else None
        return VALUE_TO_MODE_LABEL.get(value, str(value))

    async def async_select_option(self, option: str) -> None:
        # Accept the Chinese label (what the UI sends) and the legacy English
        # code, so existing scripts/automations that call this service with
        # "smart" keep working after the relabel.
        value = MODE_LABEL_TO_VALUE.get(option)
        if value is None:
            value = MODE_TO_VALUE.get(option)
        if value is None:
            raise ValueError(f"unknown clean mode {option}")
        try:
            await self.api.set_thing_params(self.device_id, {"mode": value})
        except OkpApiError as err:
            _LOGGER.warning("OKP set clean mode failed: %s", err)
            raise HomeAssistantError(f"OKP 设置清扫模式失败：{err}") from err
        self.coordinator.async_schedule_refresh()
