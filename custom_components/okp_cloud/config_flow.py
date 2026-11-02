"""Config flow for the OKP Cloud vacuum integration."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OkpApi, OkpApiError, OkpAuthError
from .const import CONF_ACCOUNT, CONF_REALTIME, CONF_REALTIME_DEFAULT, DOMAIN

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ACCOUNT, default=""): cv.string,
        vol.Required(CONF_PASSWORD, default=""): cv.string,
    }
)


class OkpOptionsFlow(OptionsFlow):
    """Options: turn the realtime push channel on or off.

    The socket is additive - entities stay correct without it - but it is the
    one part of this integration that talks to the cloud over a long-lived
    connection instead of short requests. Somebody whose account does not
    tolerate a second socket (or who simply prefers polling) can switch it off
    here instead of removing the integration.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_REALTIME,
                        default=self.config_entry.options.get(
                            CONF_REALTIME, CONF_REALTIME_DEFAULT
                        ),
                    ): cv.boolean,
                }
            ),
        )


class OkpCloudFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OKP Cloud."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OkpOptionsFlow:
        return OkpOptionsFlow()

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
        # v1.2.0: scan every home under the account (the v3.4.0 app lists
        # multiple homes; a device can live in any of them), then collect all
        # robot vacuums that have a CoolKit third_dev_id, deduplicated.
        homes = await api.get_homes()
        if not homes:
            raise OkpApiError("no homes found")
        devices: list[dict] = []
        seen: set[str] = set()
        first_home: str | None = None
        for home in homes:
            home_id = str(home.get("home_id") or home.get("id"))
            devs = await api.get_devices(home_id)
            for dev in devs:
                third = dev.get("third_dev_id")
                if third and third not in seen:
                    seen.add(third)
                    devices.append(dev)
            if devices and first_home is None:
                first_home = home_id
        if not devices:
            return None
        return api, first_home, devices

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
            # v1.2.2: the CoolKit refresh token is what renews the cloud
            # session after the OKP access token expires — without it the
            # integration goes dead a few hours after every login.
            "coolkit_rt": api.coolkit_rt,
            "coolkit_apikey": api.coolkit_apikey,
            "coolkit_region": api.coolkit_region,
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
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle a reauth request from the integration.

        Home Assistant calls this step with the *stored entry data* (not user
        input). Since the password is intentionally never persisted, indexing
        entry_data for CONF_PASSWORD raised KeyError and crashed the reauth
        task ("Task exception was never retrieved"), leaving the entry stuck
        until it was deleted and re-added. The form therefore lives in a
        separate confirm step.
        """
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show / handle the reauth form (account + password)."""
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
                    api, home_id, devices = result
                    entry = self._get_reauth_entry()
                    # Rebuild the whole payload (token + device list) so a
                    # reauth after a device was added on the app side picks
                    # the new device up instead of keeping a stale list.
                    new_data = self._entry_data(api, home_id, devices, account)
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
            step_id="reauth_confirm",
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
