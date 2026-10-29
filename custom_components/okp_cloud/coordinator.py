"""Coordinator for the OKP Cloud vacuum integration."""
from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import OkpApi, OkpApiError, OkpAuthError
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAP_CHECK_SECONDS,
    MAP_HISTORY_NUM,
    MAP_REFRESH_MINUTES,
    RELOGIN_COOLDOWN_SECONDS,
)
from .map_render import parse_map_paths, render_map_png

_LOGGER = logging.getLogger(__name__)


class OkpCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch OKP / CoolKit device state on a schedule."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: OkpApi,
        device_id: str,
        account: str | None = None,
        password: str | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.api = api
        self.device_id = device_id
        self.account = account
        self.password = password
        self.last_error: str | None = None
        # Sweep map cache: PNG bytes + the cleaning run it belongs to.
        self.map_image: bytes | None = None
        self.map_cleaning_id: str | None = None
        self.map_updated_at: float = 0.0
        self.map_error: str | None = None
        self._map_check_ts: float = 0.0
        self._next_retry_at: float = 0.0
        # Whether a reauth prompt has already been requested for this load.
        self._reauth_requested = False

    async def _maybe_trigger_reauth(self, err: OkpApiError | OkpAuthError) -> None:
        """Ask Home Assistant to start the reauth flow (user enters password).

        This is a standard HA reauth prompt — the integration never calls the
        password login endpoint by itself, so it can't kick the phone app
        session. Triggered at most once per coordinator load.
        """
        if self._reauth_requested:
            return
        self._reauth_requested = True
        try:
            entry = next(
                (
                    e
                    for e in self.hass.config_entries.async_entries(DOMAIN)
                    if not e.disabled_by
                ),
                None,
            )
            if entry:
                await entry.async_start_reauth(self.hass)
                _LOGGER.warning("OKP reauth flow started: %s", err)
        except Exception as exc:  # noqa: BLE001 - reauth is best-effort
            _LOGGER.warning("OKP could not start reauth flow: %s", exc)

    async def _async_refresh_map(self) -> None:
        """Fetch the newest cleaning run map (low frequency).

        Probes the history endpoint at most every MAP_CHECK_SECONDS; pulls a
        new map when the latest cleaningId changes or every
        MAP_REFRESH_MINUTES. Failures are logged and never block the main
        poll cycle.
        """
        now = time.time()
        if now - self._map_check_ts < MAP_CHECK_SECONDS:
            return
        self._map_check_ts = now
        try:
            histories = await self.api.get_cleaning_history(self.device_id, MAP_HISTORY_NUM)
            latest = None
            for h in histories:
                cid = h.get("cleaningId")
                if cid:
                    latest = cid
                    break
            if not latest:
                return
            due = latest != self.map_cleaning_id or (
                now - self.map_updated_at > MAP_REFRESH_MINUTES * 60
            )
            if not due:
                return
            paths = await self.api.get_cleaning_map(self.device_id, latest)
            if not paths:
                self.map_error = "no map data for latest cleaning"
                return
            points = parse_map_paths(paths)
            if not points:
                self.map_error = "map data empty"
                return
            self.map_image = render_map_png(points)
            self.map_cleaning_id = latest
            self.map_updated_at = time.time()
            self.map_error = None
            _LOGGER.debug("OKP map updated: %s (%d points)", latest, len(points))
        except (OkpApiError, OkpAuthError) as err:
            # Keep the previous image; retry next cycle.
            self.map_error = str(err)
            _LOGGER.warning("OKP map refresh failed: %s", err)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            item = await self.api.get_thing_state(self.device_id)
        except OkpAuthError:
            # CoolKit token expired/rejected: silently refresh the CoolKit
            # token using the stored OKP access token. This never calls the
            # password login endpoint, so it cannot kick the phone app
            # session (OKP cloud allows only one active session per account).
            now = time.time()
            if now < self._next_retry_at:
                raise UpdateFailed("auth failed, retrying later") from None
            self._next_retry_at = now + RELOGIN_COOLDOWN_SECONDS
            try:
                await self.api.refresh_coolkit_token()
                item = await self.api.get_thing_state(self.device_id)
            except (OkpApiError, OkpAuthError) as err:
                self.last_error = str(err)
                _LOGGER.warning(
                    "OKP auth failed, re-auth needed in Home Assistant: %s", err
                )
                await self._maybe_trigger_reauth(err)
                raise UpdateFailed(str(err)) from err
        except OkpApiError as err:
            self.last_error = str(err)
            _LOGGER.warning("OKP state fetch failed: %s", err)
            raise UpdateFailed(str(err)) from err
        self.last_error = None
        await self._async_refresh_map()
        return {
            "item": item,
            "params": item.get("params") or {},
            "online": bool(item.get("online")),
            "devicekey": item.get("devicekey"),
            "fw_version": (item.get("params") or {}).get("fwVersion"),
        }
