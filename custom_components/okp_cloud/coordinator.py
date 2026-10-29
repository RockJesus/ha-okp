"""Coordinator for the OKP Cloud vacuum integration."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import OkpApi, OkpApiError, OkpAuthError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

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

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            item = await self.api.get_thing_state(self.device_id)
        except OkpAuthError:
            # token expired / rejected: re-login once with stored credentials
            if self.account and self.password:
                try:
                    await self.api.login(self.account, self.password)
                    # Re-login also invalidates the CoolKit token; force a
                    # fresh refresh so the retried thing request works.
                    await self.api.refresh_coolkit_token()
                    item = await self.api.get_thing_state(self.device_id)
                except (OkpApiError, OkpAuthError) as err:
                    self.last_error = str(err)
                    _LOGGER.warning("OKP re-login failed: %s", err)
                    raise UpdateFailed(str(err)) from err
            else:
                self.last_error = "auth failed, re-login needed"
                raise UpdateFailed("auth failed, re-login needed")
        except OkpApiError as err:
            self.last_error = str(err)
            _LOGGER.warning("OKP state fetch failed: %s", err)
            raise UpdateFailed(str(err)) from err
        self.last_error = None
        return {
            "item": item,
            "params": item.get("params") or {},
            "online": bool(item.get("online")),
            "devicekey": item.get("devicekey"),
            "fw_version": (item.get("params") or {}).get("fwVersion"),
        }
