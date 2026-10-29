"""OKP Cloud vacuum integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import OkpApi
from .const import DOMAIN, PLATFORMS
from .coordinator import OkpCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OKP Cloud from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    session = async_create_clientsession(hass)
    api = OkpApi(session)
    api.access_token = entry.data.get("access_token")
    api.user_id = entry.data.get("user_id")
    # Reuse a stored CoolKit token when available (avoids an extra refresh
    # request on startup); it is renewed silently when expired.
    api.coolkit_at = entry.data.get("coolkit_at")
    if api.coolkit_at:
        api.coolkit_at_expire = int(entry.data.get("coolkit_at_expire") or 0)

    coordinator = OkpCoordinator(
        hass,
        api,
        entry.data["third_dev_id"],
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
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
