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
        self._next_relogin_at: float = 0.0

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
            # token expired / rejected: re-login once with stored credentials.
            # Back off after a failed login so we never hammer the auth
            # endpoint (login storms can trip cloud risk control and break
            # the phone app session).
            if time.time() < self._next_relogin_at:
                self.last_error = "auth failed, retrying later"
                raise UpdateFailed("auth failed, retrying later") from None
            if self.account and self.password:
                try:
                    await self.api.login(self.account, self.password)
                    # Re-login also invalidates the CoolKit token; force a
                    # fresh refresh so the retried thing request works.
                    await self.api.refresh_coolkit_token()
                    item = await self.api.get_thing_state(self.device_id)
                except (OkpApiError, OkpAuthError) as err:
                    self.last_error = str(err)
                    self._next_relogin_at = time.time() + RELOGIN_COOLDOWN_SECONDS
                    _LOGGER.warning("OKP re-login failed, backing off: %s", err)
                    raise UpdateFailed(str(err)) from err
            else:
                self.last_error = "auth failed, re-login needed"
                raise UpdateFailed("auth failed, re-login needed")
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
