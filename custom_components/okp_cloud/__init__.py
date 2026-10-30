"""OKP Cloud vacuum integration."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import OkpApi
from .const import CONF_PASSWORD, DOMAIN, PLATFORMS
from .coordinator import OkpCoordinator

_LOGGER = logging.getLogger(__name__)

# Devices list storage key inside entry.data (v1.1.9+).
DEVICES_KEY = "devices"


def _device_list(entry: ConfigEntry) -> list[dict]:
    """Resolve the device list from entry.data (legacy entries migrate on setup)."""
    devices = entry.data.get(DEVICES_KEY)
    if isinstance(devices, list) and devices:
        return devices
    # Legacy (< v1.1.9) entry: single flat device fields.
    third_dev_id = entry.data.get("third_dev_id")
    if third_dev_id:
        return [
            {
                "id": entry.data.get("device_id"),
                "name": entry.data.get("device_name"),
                "third_dev_id": third_dev_id,
                "product_id": entry.data.get("product_id"),
                "model": entry.data.get("model"),
            }
        ]
    return []


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OKP Cloud from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    # Migration (v1.1.8): entries created before this version may still hold
    # a plain-text password in data; drop it now that the integration runs
    # purely on the CoolKit token (login only happens transiently in flows).
    # NB: ConfigEntry.data is read-only on newer HA — always go through
    # async_update_entry, never assign entry.data directly (raises
    # "data cannot be changed directly" and aborts setup).
    new_data = {k: v for k, v in entry.data.items() if k != CONF_PASSWORD}
    # Migration (v1.1.9): backfill the devices list for legacy entries.
    devices = _device_list(entry)
    if not devices:
        raise ValueError("no devices in config entry data")
    if DEVICES_KEY not in entry.data:
        new_data[DEVICES_KEY] = devices
    if new_data != entry.data:
        hass.config_entries.async_update_entry(entry, data=new_data)

    session = async_create_clientsession(hass)
    api = OkpApi(session)
    api.access_token = entry.data.get("access_token")
    api.user_id = entry.data.get("user_id")
    # Reuse a stored CoolKit token when available (avoids an extra refresh
    # request on startup); it is renewed silently when expired.
    api.coolkit_at = entry.data.get("coolkit_at")
    if api.coolkit_at:
        api.coolkit_at_expire = int(entry.data.get("coolkit_at_expire") or 0)

    # One coordinator per robot: independent poll cycle, map cache and
    # per-device entity state.
    coordinators: dict[str, OkpCoordinator] = {}
    for dev in devices:
        third = dev.get("third_dev_id")
        if not third:
            continue
        coordinators[third] = OkpCoordinator(hass, api, third)

    # First refresh for every coordinator (parallel) before platforms load.
    if coordinators:
        await asyncio.gather(
            *(c.async_config_entry_first_refresh() for c in coordinators.values())
        )

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinators": coordinators,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # Session is created via async_create_clientsession(hass) and is
        # managed by Home Assistant; integrations must NOT close it
        # (deprecated since HA 2026.x, will fail in 2027.9).
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
