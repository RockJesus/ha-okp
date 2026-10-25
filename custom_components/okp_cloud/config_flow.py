"""Config flow for the OKP Cloud vacuum integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD
from homeassistant.helpers import config_validation as cv

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

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            account = user_input[CONF_ACCOUNT].strip()
            password = user_input[CONF_PASSWORD]
            session = aiohttp.ClientSession()
            api = OkpApi(session)
            try:
                await api.login(account, password)
                home_id = await api.get_home_id()
                devices = await api.get_devices(home_id)
                detail = None
                device = None
                for dev in devices:
                    if dev.get("third_dev_id"):
                        device = dev
                        detail = await api.get_device_detail(home_id, str(dev.get("id")))
                        break
                if device is None:
                    errors["base"] = "no_device"
                else:
                    await self.async_set_unique_id(f"okp-{account}")
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"OKP {device.get('name', '扫地机器人')}",
                        data={
                            CONF_ACCOUNT: account,
                            CONF_PASSWORD: password,
                            "user_id": api.user_id,
                            "access_token": api.access_token,
                            "home_id": home_id,
                            "device_id": str(device.get("id")),
                            "device_name": device.get("name"),
                            "third_dev_id": device.get("third_dev_id"),
                            "product_id": device.get("third_product_id_tuya"),
                            "model": device.get("device_model_name"),
                            "detail": detail or {},
                        },
                    )
            except OkpAuthError:
                errors["base"] = "invalid_auth"
            except OkpApiError as err:
                _LOGGER.warning("OKP API error during setup: %s", err)
                errors["base"] = "cannot_connect"
            except aiohttp.ClientError as err:
                _LOGGER.warning("OKP network error during setup: %s", err)
                errors["base"] = "cannot_connect"
            finally:
                await session.close()

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_user(user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_user(user_input)
