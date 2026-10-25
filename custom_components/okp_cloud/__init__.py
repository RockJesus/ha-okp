"""OKP Cloud vacuum integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import OkpApi
from .const import CONF_ACCOUNT, CONF_PASSWORD, DOMAIN, PLATFORMS
from .coordinator import OkpCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OKP Cloud from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    session = async_create_clientsession(hass)
    api = OkpApi(session)
    api.access_token = entry.data.get("access_token")
    api.user_id = entry.data.get("user_id")

    coordinator = OkpCoordinator(
        hass,
        api,
        entry.data["third_dev_id"],
        account=entry.data.get(CONF_ACCOUNT),
        password=entry.data.get(CONF_PASSWORD),
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
        "session": session,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data["session"].close()
    return unload_ok
