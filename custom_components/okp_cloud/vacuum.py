"""Vacuum platform for the OKP Cloud integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import OkpApi, OkpApiError
from .const import (
    DOMAIN,
    FAN_QUIET,
    FAN_SPEED_LIST,
    FAN_STANDARD,
    FAN_STRONG,
    MODE_LIST,
    MODE_RANDOM,
    MODE_SMART,
    MODE_SPIRAL,
    MODE_WALL_FOLLOW,
)
from .coordinator import OkpCoordinator

_LOGGER = logging.getLogger(__name__)

FAN_SPEED_TO_WIND = {FAN_QUIET: 0, FAN_STANDARD: 1, FAN_STRONG: 2}
WIND_TO_FAN_SPEED = {v: k for k, v in FAN_SPEED_TO_WIND.items()}
MODE_TO_VALUE = {MODE_SMART: 0, MODE_RANDOM: 1, MODE_WALL_FOLLOW: 2, MODE_SPIRAL: 3}
VALUE_TO_MODE = {v: k for k, v in MODE_TO_VALUE.items()}


def _clean_state(params: dict[str, Any]) -> str:
    """Derive HA vacuum state from CoolKit params."""
    sweep = params.get("sweep")
    wstate = params.get("wstate")
    if sweep == 1:
        return "cleaning"
    if wstate in (3, "3"):
        return "returning"
    if wstate in (2, "2"):
        return "paused"
    return "idle"


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
    async_add_entities([OkpVacuum(coordinator, api, device_id, name, model)])


class OkpVacuum(CoordinatorEntity[OkpCoordinator], StateVacuumEntity):
    """OKP cloud vacuum entity."""

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
        self._attr_name = "扫地机器人"
        self._attr_unique_id = f"okp_cloud_{device_id}"
        self._attr_model = model
        self._attr_manufacturer = "OKP"
        self._attr_supported_features = (
            VacuumEntityFeature.START
            | VacuumEntityFeature.PAUSE
            | VacuumEntityFeature.STOP
            | VacuumEntityFeature.RETURN_HOME
            | VacuumEntityFeature.FAN_SPEED
            | VacuumEntityFeature.BATTERY
            | VacuumEntityFeature.STATE
            | VacuumEntityFeature.STATUS
        )
        self._attr_fan_speed_list = FAN_SPEED_LIST
        self._attr_available = True

    @property
    def _params(self) -> dict[str, Any]:
        return self.coordinator.data.get("params", {}) if self.coordinator.data else {}

    @property
    def state(self) -> str:
        return _clean_state(self._params)

    @property
    def battery_level(self) -> int | None:
        power = self._params.get("power")
        try:
            return int(power)
        except (TypeError, ValueError):
            return None

    @property
    def fan_speed(self) -> str | None:
        wind = self._params.get("wind")
        try:
            return WIND_TO_FAN_SPEED.get(int(wind))
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        p = self._params
        attrs: dict[str, Any] = {
            "work_state": p.get("wstate"),
            "clean_mode": VALUE_TO_MODE.get(p.get("mode", 0), p.get("mode")),
            "sweep_switch": p.get("sweep"),
            "power_switch": p.get("switch"),
            "fault_code": p.get("fault"),
            "rssi": p.get("rssi"),
            "firmware_version": p.get("fwVersion"),
            "cleaning_area": p.get("cleaningArea"),
            "cleaning_times": p.get("cleaningTimes"),
            "carpet_booster": p.get("carpetBooster"),
            "online": self.coordinator.data.get("online") if self.coordinator.data else None,
        }
        if self.coordinator.data:
            attrs["device_key"] = self.coordinator.data.get("devicekey")
        if getattr(self.coordinator, "_last_error", None):
            attrs["last_error"] = self.coordinator._last_error
        return attrs

    # -- control -----------------------------------------------------------

    async def async_start(self) -> None:
        await self._set({"switch": 1, "sweep": 1})

    async def async_pause(self) -> None:
        await self._set({"sweep": 0})

    async def async_stop(self, **kwargs: Any) -> None:
        await self._set({"sweep": 0, "switch": 0})

    async def async_return_to_base(self, **kwargs: Any) -> None:
        # CoolKit has no dedicated "return" dp; stopping the sweep makes the
        # robot return to the dock on most Lefant/OKP units.
        await self._set({"sweep": 0})

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        wind = FAN_SPEED_TO_WIND.get(fan_speed)
        if wind is None:
            raise ValueError(f"unknown fan speed {fan_speed}")
        await self._set({"wind": wind})

    async def _set(self, params: dict[str, Any]) -> None:
        try:
            await self.api.set_thing_params(self.device_id, params)
        except OkpApiError as err:
            _LOGGER.warning("OKP control failed: %s", err)
            raise
