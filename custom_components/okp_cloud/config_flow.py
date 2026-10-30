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

    async def _validate_login(
        self, account: str, password: str
    ) -> tuple[OkpApi, str, list[dict]] | None:
        """Login to the OKP cloud and fetch all vacuum devices.

        Returns (api, home_id, devices) or None when no vacuum device is found.
        Raises OkpAuthError / OkpApiError / aiohttp.ClientError on failure.
        """
        # Use HA's shared client session (managed by HA, never closed here).
        session = async_get_clientsession(self.hass)
        api = OkpApi(session)
        await api.login(account, password)
        # Immediately exchange the OKP access token for a long-lived CoolKit
        # token (multi-client, shares the cloud session without kicking the
        # phone app). Store it so HA restarts never need the OKP login again.
        await api.refresh_coolkit_token()
        home_id = await api.get_home_id()
        devices = await api.get_devices(home_id)
        # v1.1.9: support every robot vacuum under the account (all devices
        # with a CoolKit third_dev_id), not just the first one.
        devices = [dev for dev in devices if dev.get("third_dev_id")]
        if not devices:
            return None
        return api, home_id, devices

    def _entry_data(
        self, api: OkpApi, home_id: str, devices: list[dict], account: str
    ) -> dict[str, Any]:
        """Build a minimal, privacy-aware config entry payload.

        Keeps the flat first-device fields (device_id/third_dev_id/...) for
        backward compatibility and stores the full `devices` list so every
        robot under the account is managed by this single entry.
        """
        # Privacy: never persist the plain-text password. The integration
        # runs in pure CoolKit-token mode and only needs it transiently
        # for the login call during setup/reauth (OKP is a single-session
        # cloud; keeping the password off disk also protects it from the
        # HAOS .storage file being read over the LAN).
        first = devices[0]
        device_list = []
        for dev in devices:
            entry = {
                "id": str(dev.get("id")),
                "name": dev.get("name"),
                "third_dev_id": dev.get("third_dev_id"),
                "product_id": dev.get("third_product_id_tuya"),
                "model": dev.get("device_model_name"),
            }
            if entry not in device_list:
                device_list.append(entry)
        return {
            CONF_ACCOUNT: account,
            "user_id": api.user_id,
            "access_token": api.access_token,
            # Keep the CoolKit token so HA restarts reuse the same cloud
            # session instead of logging in again (login kicks the phone
            # app session on OKP's single-session cloud).
            "coolkit_at": api.coolkit_at,
            "coolkit_at_expire": api.coolkit_at_expire,
            "home_id": home_id,
            # flat first-device fields (legacy)
            "device_id": first.get("id"),
            "device_name": first.get("name"),
            "third_dev_id": first.get("third_dev_id"),
            "product_id": first.get("third_product_id_tuya"),
            "model": first.get("device_model_name"),
            # all devices (v1.1.9+)
            "devices": device_list,
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
                    api, home_id, devices = result
                    await self.async_set_unique_id(f"okp-{account}")
                    self._abort_if_unique_id_configured()
                    names = "、".join(
                        str(d.get("name")) for d in devices[:5] if d.get("name")
                    )
                    title = (
                        f"OKP {names}"
                        if len(devices) > 1
                        else f"OKP {devices[0].get('name', '扫地机器人')}"
                    )
                    return self.async_create_entry(
                        title=title,
                        data=self._entry_data(api, home_id, devices, account),
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

    def _auth_schema(self, account: str = "") -> vol.Schema:
        """Login form with the account prefilled for reauth/reconfigure."""
        return vol.Schema(
            {
                vol.Required(CONF_ACCOUNT, default=account): cv.string,
                vol.Required(CONF_PASSWORD, default=""): cv.string,
            }
        )

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-authenticate an existing entry (e.g. after token expiry)."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        account = (entry.data.get(CONF_ACCOUNT) or "") if entry else ""
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
            data_schema=self._auth_schema(account),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure an existing entry (change account/password)."""
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        account = (entry.data.get(CONF_ACCOUNT) or "") if entry else ""
        if user_input is not None:
            account = user_input[CONF_ACCOUNT].strip()
            password = user_input[CONF_PASSWORD]
            try:
                result = await self._validate_login(account, password)
                if result is None:
                    errors["base"] = "no_device"
                else:
                    api, home_id, devices = result
                    entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
                    # Rebuild the full payload (token + device list).
                    new_data = self._entry_data(api, home_id, devices, account)
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
            data_schema=self._auth_schema(account),
            errors=errors,
        )
