"""Config flow for the OKP Cloud vacuum integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OkpApi, OkpApiError, OkpAuthError
from .const import CONF_ACCOUNT, DOMAIN

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ACCOUNT, default=""): cv.string,
        vol.Required(CONF_PASSWORD, default=""): cv.string,
    }
)


class OkpCloudFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OKP Cloud."""

    VERSION = 1

    async def _validate_login(self, account: str, password: str) -> tuple[OkpApi, str, dict] | None:
        """Login to the OKP cloud and fetch the first vacuum device.

        Returns (api, home_id, device) or None when no vacuum device is found.
        Raises OkpAuthError / OkpApiError / aiohttp.ClientError on failure.
        """
        # Use HA's shared client session (managed by HA, never closed here).
        session = async_get_clientsession(self.hass)
        api = OkpApi(session)
        await api.login(account, password)
        home_id = await api.get_home_id()
        devices = await api.get_devices(home_id)
        device = next((dev for dev in devices if dev.get("third_dev_id")), None)
        if device is None:
            return None
        return api, home_id, device

    def _entry_data(self, api: OkpApi, home_id: str, device: dict, account: str, password: str) -> dict[str, Any]:
        """Build a minimal, privacy-aware config entry payload."""
        return {
            CONF_ACCOUNT: account,
            CONF_PASSWORD: password,
            "user_id": api.user_id,
            "access_token": api.access_token,
            # Keep the CoolKit token so HA restarts reuse the same cloud
            # session instead of logging in again (login kicks the phone
            # app session on OKP's single-session cloud).
            "coolkit_at": api.coolkit_at,
            "coolkit_at_expire": api.coolkit_at_expire,
            "home_id": home_id,
            "device_id": str(device.get("id")),
            "device_name": device.get("name"),
            "third_dev_id": device.get("third_dev_id"),
            "product_id": device.get("third_product_id_tuya"),
            "model": device.get("device_model_name"),
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            account = user_input[CONF_ACCOUNT].strip()
            password = user_input[CONF_PASSWORD]
            try:
                result = await self._validate_login(account, password)
                if result is None:
                    errors["base"] = "no_device"
                else:
                    api, home_id, device = result
                    await self.async_set_unique_id(f"okp-{account}")
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"OKP {device.get('name', '扫地机器人')}",
                        data=self._entry_data(api, home_id, device, account, password),
                    )
            except OkpAuthError:
                errors["base"] = "invalid_auth"
            except OkpApiError as err:
                _LOGGER.warning("OKP API error during setup: %s", err)
                errors["base"] = "cannot_connect"
            except aiohttp.ClientError as err:
                _LOGGER.warning("OKP network error during setup: %s", err)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-authenticate an existing entry (e.g. after token expiry)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            account = user_input[CONF_ACCOUNT].strip()
            password = user_input[CONF_PASSWORD]
            try:
                result = await self._validate_login(account, password)
                if result is None:
                    errors["base"] = "no_device"
                else:
                    api, home_id, device = result
                    entry = self._get_reauth_entry()
                    new_data = {
                        **entry.data,
                        CONF_PASSWORD: password,
                        "access_token": api.access_token,
                        "user_id": api.user_id,
                        "coolkit_at": api.coolkit_at,
                        "coolkit_at_expire": api.coolkit_at_expire,
                    }
                    self.hass.config_entries.async_update_entry(entry, data=new_data)
                    return self.async_abort(reason="reauth_successful")
            except OkpAuthError:
                errors["base"] = "invalid_auth"
            except OkpApiError as err:
                _LOGGER.warning("OKP API error during reauth: %s", err)
                errors["base"] = "cannot_connect"
            except aiohttp.ClientError as err:
                _LOGGER.warning("OKP network error during reauth: %s", err)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reauth",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure an existing entry (change account/password)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            account = user_input[CONF_ACCOUNT].strip()
            password = user_input[CONF_PASSWORD]
            try:
                result = await self._validate_login(account, password)
                if result is None:
                    errors["base"] = "no_device"
                else:
                    api, home_id, device = result
                    entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
                    new_data = self._entry_data(api, home_id, device, account, password)
                    self.hass.config_entries.async_update_entry(entry, data=new_data)
                    return self.async_abort(reason="reconfigure_successful")
            except OkpAuthError:
                errors["base"] = "invalid_auth"
            except OkpApiError as err:
                _LOGGER.warning("OKP API error during reconfigure: %s", err)
                errors["base"] = "cannot_connect"
            except aiohttp.ClientError as err:
                _LOGGER.warning("OKP network error during reconfigure: %s", err)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )
