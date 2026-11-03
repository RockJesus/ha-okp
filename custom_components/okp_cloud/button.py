"""Button platform for the OKP Cloud vacuum integration.

Two kinds of buttons live here:

* "查找机器人" - the v3.4.0 app writes ``{"call": 1}`` and the robot beeps, so
  you can locate it under a sofa. Earlier builds exposed ``call`` as a
  diagnostic *sensor*, which made an action look like a number.
* Manual remote (v1.4.2) - the app's joystick writes ``{"move": N}`` while a
  direction is held and ``{"move": 4}`` on release. A button cannot be held
  down, so each press is a short nudge (``MOVE_BUTTON_SECONDS``); for a real
  joystick or a longer drive use the ``okp_cloud.move`` service instead.
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
from .const import CALL_DP, DOMAIN, MOVE_DIRECTIONS, MOVE_RELEASE_VALUE, entity_scope
from .coordinator import OkpCoordinator

_LOGGER = logging.getLogger(__name__)

# A nudge long enough to be visible, short enough that a mis-tap cannot send
# the robot across the room. Longer drives belong in the service, where the
# duration is explicit.
MOVE_BUTTON_SECONDS = 0.5

# (translation key, icon, move dp value)
MOVE_BUTTONS: tuple[tuple[str, str, int], ...] = (
    ("move_forward", "mdi:arrow-up-bold", MOVE_DIRECTIONS["forward"]),
    ("move_backward", "mdi:arrow-down-bold", MOVE_DIRECTIONS["backward"]),
    ("move_left", "mdi:arrow-left-bold", MOVE_DIRECTIONS["left"]),
    ("move_right", "mdi:arrow-right-bold", MOVE_DIRECTIONS["right"]),
    ("move_stop", "mdi:stop-circle-outline", MOVE_RELEASE_VALUE),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    api: OkpApi = hass.data[DOMAIN][entry.entry_id]["api"]
    coordinators: dict[str, OkpCoordinator] = hass.data[DOMAIN][entry.entry_id]["coordinators"]
    entities = []
    scope = entity_scope(entry)
    for dev in entry.data.get("devices", []):
        third = dev.get("third_dev_id")
        coordinator = coordinators.get(third)
        if coordinator is None:
            continue
        name = dev.get("name") or "OKP 扫地机器人"
        model = dev.get("model")
        entities.append(OkpFindRobotButton(coordinator, api, third, name, model, scope=scope))
        for key, icon, value in MOVE_BUTTONS:
            entities.append(
                OkpMoveButton(coordinator, api, third, name, model, key, icon, value, scope=scope)
            )
    async_add_entities(entities)


class _OkpButtonBase(CoordinatorEntity[OkpCoordinator], ButtonEntity):
    """Shared device wiring for the integration's buttons."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OkpCoordinator,
        api: OkpApi,
        device_id: str,
        name: str,
        model: str | None,
        key: str,
        scope: str = "",
    ) -> None:
        super().__init__(coordinator)
        self.api = api
        self.device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{key}{scope}"
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


class OkpFindRobotButton(_OkpButtonBase):
    """Make the robot beep ("查找机器人")."""

    _attr_translation_key = "find_robot"
    _attr_icon = "mdi:bullhorn"

    def __init__(
        self,
        coordinator: OkpCoordinator,
        api: OkpApi,
        device_id: str,
        name: str,
        model: str | None,
        scope: str = "",
    ) -> None:
        super().__init__(coordinator, api, device_id, name, model, "find_robot")

    async def async_press(self) -> None:
        try:
            await self.api.set_thing_params(self.device_id, {CALL_DP: 1})
        except OkpApiError as err:
            _LOGGER.warning("OKP find-robot failed: %s", err)
            raise HomeAssistantError(f"OKP 查找机器人失败：{err}") from err
        self.coordinator.async_schedule_refresh((4.0,))


class OkpMoveButton(_OkpButtonBase):
    """One direction of the manual remote, as a fixed-length nudge."""

    def __init__(
        self,
        coordinator: OkpCoordinator,
        api: OkpApi,
        device_id: str,
        name: str,
        model: str | None,
        key: str,
        icon: str,
        value: int,
        scope: str = "",
    ) -> None:
        super().__init__(coordinator, api, device_id, name, model, key)
        self._attr_translation_key = key
        self._attr_icon = icon
        self._move_value = value

    async def async_press(self) -> None:
        duration = 0 if self._move_value == MOVE_RELEASE_VALUE else MOVE_BUTTON_SECONDS
        try:
            await self.coordinator.async_move(self._move_value, duration)
        except OkpApiError as err:
            _LOGGER.warning("OKP manual move failed: %s", err)
            raise HomeAssistantError(f"OKP 手动遥控失败：{err}") from err
        self.coordinator.async_schedule_refresh((3.0,))
