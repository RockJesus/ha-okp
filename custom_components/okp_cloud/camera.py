"""Camera platform: shows the latest OKP sweep map as a PNG image."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, entity_scope
from .coordinator import OkpCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinators: dict[str, OkpCoordinator] = hass.data[DOMAIN][entry.entry_id]["coordinators"]
    entities = []
    scope = entity_scope(hass, entry)
    for dev in entry.data.get("devices", []):
        third = dev.get("third_dev_id")
        coordinator = coordinators.get(third)
        if coordinator is None:
            continue
        entities.append(
            OkpMapCamera(
                coordinator,
                third,
                dev.get("name") or "OKP 扫地机器人",
                dev.get("model"),
                scope=scope,
            )
        )
    async_add_entities(entities)


class OkpMapCamera(CoordinatorEntity[OkpCoordinator], Camera):
    """Camera entity serving the rendered sweep map PNG."""

    _attr_has_entity_name = True
    _attr_translation_key = "map"

    def __init__(
        self,
        coordinator: OkpCoordinator,
        device_id: str,
        name: str,
        model: str | None,
        scope: str = "",
    ) -> None:
        super().__init__(coordinator)
        # CoordinatorEntity.__init__ does not chain to Camera.__init__,
        # which is required for provider attributes (_webrtc_provider etc).
        Camera.__init__(self)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_map{scope}"
        # No ON_OFF feature: this camera only serves the rendered map image
        # (a toggle button without turn_on/turn_off would error in the UI).
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=name,
            manufacturer="OKP",
            model=model or "OKP 扫地机器人",
        )

    @property
    def available(self) -> bool:
        """Always available: keep the last known image."""
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose which run the picture belongs to (v1.3.1).

        Without this the camera silently serves an old image when the newest
        run's map is not ready, and there is no way to tell from the UI whether
        the picture is fresh - which makes "map looks wrong" impossible to
        diagnose.
        """
        updated = self.coordinator.map_updated_at
        return {
            "map_id": self.coordinator.map_cleaning_id,
            "map_updated_at": (
                datetime.fromtimestamp(updated, tz=timezone.utc).isoformat()
                if updated
                else None
            ),
            "last_error": self.coordinator.map_error,
        }

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the last rendered map PNG (no resizing)."""
        return self.coordinator.map_image
