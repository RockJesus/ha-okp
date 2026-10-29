"""Camera platform: shows the latest OKP sweep map as a PNG image."""
from __future__ import annotations

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OkpCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: OkpCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    device_id = entry.data.get("third_dev_id") or entry.data.get("device_id")
    name = entry.data.get("device_name") or "OKP 扫地机器人"
    model = entry.data.get("model")
    async_add_entities([OkpMapCamera(coordinator, device_id, name, model)])


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
    ) -> None:
        super().__init__(coordinator)
        # CoordinatorEntity.__init__ does not chain to Camera.__init__,
        # which is required for provider attributes (_webrtc_provider etc).
        Camera.__init__(self)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_map"
        self._attr_supported_features = getattr(CameraEntityFeature, "ON_OFF", 0)
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

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the last rendered map PNG (no resizing)."""
        return self.coordinator.map_image
