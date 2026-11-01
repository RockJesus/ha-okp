"""OKP Cloud vacuum integration."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import OkpApi, OkpApiError, OkpAuthError
from .const import (
    AT_LIFETIME_FALLBACK_SECONDS,
    CONF_PASSWORD,
    DOMAIN,
    PLATFORMS,
    SERVICE_REFRESH_SESSION,
)
from .coordinator import OkpCoordinator

_LOGGER = logging.getLogger(__name__)

# Devices list storage key inside entry.data (v1.1.9+).
DEVICES_KEY = "devices"


async def _async_refresh_session(call: ServiceCall) -> dict[str, Any]:
    """Force a CoolKit session renewal and report the outcome.

    v1.2.9: the access token is long-lived (weeks), so the ``rt`` renewal path
    would otherwise only be exercised when it is already too late to tell a
    working renewal from a lucky cache hit. This service exercises the same
    code the poll cycle uses, and answers with the new session state so the
    result is observable from the developer tools UI.
    """
    hass: HomeAssistant = call.hass
    entries: list[dict[str, Any]] = []
    for entry_id, store in (hass.data.get(DOMAIN) or {}).items():
        if not isinstance(store, dict) or "api" not in store:
            continue
        api: OkpApi = store["api"]
        coordinators: dict[str, OkpCoordinator] = store.get("coordinators") or {}
        refreshed_by: str | None = None
        error: str | None = None

        renewed = False
        try:
            renewed = await api.refresh_coolkit_by_rt()
        except (OkpApiError, OkpAuthError) as err:
            error = str(err)
        if renewed:
            refreshed_by = "rt"
        else:
            # No usable refresh token (or the gateway refused it): fall back
            # to the okplife route, which needs a live OKP access token.
            rt_error = error or "no refresh token stored"
            try:
                await api.refresh_coolkit_token()
                refreshed_by = "okplife"
                error = f"rt unavailable ({rt_error})"
            except (OkpApiError, OkpAuthError) as err2:
                error = f"rt: {rt_error}; okplife: {err2}"

        if refreshed_by:
            for coordinator in coordinators.values():
                coordinator.async_persist_tokens(force=True)

        entries.append(
            {
                "entry_id": entry_id,
                "refreshed_by": refreshed_by,
                "session_state": api.session_state,
                "has_refresh_token": bool(api.coolkit_rt),
                "token_expires_at": api.coolkit_at_expire or None,
                "token_expires_in_seconds": (
                    max(0, api.coolkit_at_expire - int(time.time()))
                    if api.coolkit_at_expire
                    else None
                ),
                "token_expiry_source": (
                    "inferred" if api.at_expire_inferred else "cloud"
                ),
                "refresh_fields": api.last_refresh_fields,
                "at_lifetime_hours": round(api.at_lifetime / 3600, 1),
                "error": error,
            }
        )
        if refreshed_by:
            _LOGGER.info("OKP session renewed on demand via %s", refreshed_by)
        else:
            _LOGGER.warning("OKP on-demand renewal failed: %s", error)

    return {"entries": entries}


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the integration services once."""
    if hass.services.has_service(DOMAIN, SERVICE_REFRESH_SESSION):
        return
    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_SESSION,
        _async_refresh_session,
        supports_response=SupportsResponse.ONLY,
    )


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

    _async_register_services(hass)

    session = async_create_clientsession(hass)
    api = OkpApi(session)
    api.access_token = entry.data.get("access_token")
    api.user_id = entry.data.get("user_id")
    # Reuse a stored CoolKit token pair when available (avoids an extra
    # refresh request on startup). The refresh token is what keeps the
    # session alive once the OKP access token expires, so it is restored
    # alongside the access token.
    api.coolkit_at = entry.data.get("coolkit_at")
    api.coolkit_rt = entry.data.get("coolkit_rt")
    api.coolkit_apikey = entry.data.get("coolkit_apikey")
    api.coolkit_region = entry.data.get("coolkit_region")
    if api.coolkit_at:
        api.coolkit_at_expire = int(entry.data.get("coolkit_at_expire") or 0)
        # v1.2.12: keep the diagnostic honest across restarts - an expiry that
        # was inferred locally must not be reported as cloud-provided.
        api.at_expire_inferred = bool(entry.data.get("coolkit_at_expire_inferred"))
    api.at_lifetime = int(
        entry.data.get("coolkit_at_lifetime") or 0
    ) or AT_LIFETIME_FALLBACK_SECONDS

    # Upgrade path for entries created before v1.2.2 (only `coolkit_at` was
    # stored): mint a refresh token while the OKP access token still works,
    # otherwise the session dies as soon as the CoolKit token expires.
    if not api.coolkit_rt and api.access_token:
        try:
            await api.refresh_coolkit_token()
            new_data = {
                **entry.data,
                "coolkit_at": api.coolkit_at,
                "coolkit_at_expire": api.coolkit_at_expire,
                "coolkit_rt": api.coolkit_rt,
                "coolkit_apikey": api.coolkit_apikey,
                "coolkit_region": api.coolkit_region,
            }
            if new_data != entry.data:
                hass.config_entries.async_update_entry(entry, data=new_data)
                _LOGGER.debug("OKP CoolKit refresh token captured on setup")
        except (OkpApiError, OkpAuthError) as err:
            # Non-fatal: the poll cycle retries and raises reauth if needed.
            _LOGGER.debug("OKP could not capture a CoolKit refresh token: %s", err)

    # One coordinator per robot: independent poll cycle, map cache and
    # per-device entity state.
    coordinators: dict[str, OkpCoordinator] = {}
    for dev in devices:
        third = dev.get("third_dev_id")
        if not third:
            continue
        coordinators[third] = OkpCoordinator(hass, api, third, entry.entry_id)

    # First refresh for every coordinator (parallel) before platforms load.
    #
    # A failed first refresh normally raises ConfigEntryNotReady and parks the
    # whole entry in HA's "retrying setup" loop. That is the wrong signal here:
    # the only realistic cause is an expired cloud session, which needs a
    # reauth prompt — not a retry loop that hides every entity. Load the
    # platforms anyway; the coordinator keeps polling and the reauth repair
    # appears after REAUTH_AFTER_FAILURES cycles.
    if coordinators:
        results = await asyncio.gather(
            *(c.async_config_entry_first_refresh() for c in coordinators.values()),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                _LOGGER.warning(
                    "OKP first refresh failed (will retry on poll): %s", result
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
