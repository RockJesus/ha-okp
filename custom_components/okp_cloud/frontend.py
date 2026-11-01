"""Frontend plumbing for the optional joystick card.

Home Assistant has no joystick entity and no stock card that can express the
"press / release" gesture the ``move`` dp speaks, so the card lives in the
frontend and calls ``okp_cloud.move``. This module only does the plumbing:

* serve ``custom_components/okp_cloud/www`` at ``/okp_cloud_static``;
* register that file as a Lovelace resource so the card shows up in the
  card picker after an update (best effort — YAML-mode dashboards have no
  writable resource collection, in which case the user adds it by hand).

Nothing here is required for the integration itself: if any step fails the
entities keep working and only the card has to be added manually.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STATIC_URL = "/okp_cloud_static"
CARD_URL_PATH = f"{STATIC_URL}/okp-joystick-card.js"
_DATA_FRONTEND = f"{DOMAIN}_frontend_registered"
_LOVELACE_DATA = "lovelace"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the card file and try to register it as a Lovelace resource."""
    if hass.data.get(_DATA_FRONTEND):
        return

    www = Path(__file__).parent / "www"
    if not www.is_dir():
        return

    try:
        # HA >= 2024.7
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(www), False)]
        )
    except ImportError:  # pragma: no cover - older HA
        hass.http.register_static_path(STATIC_URL, str(www), False)
    except Exception as err:  # noqa: BLE001 - never break setup over the card
        _LOGGER.warning("OKP 摇杆卡静态路径注册失败：%s", err)
        return

    hass.data[_DATA_FRONTEND] = True
    _LOGGER.debug("OKP 摇杆卡已挂到 %s", CARD_URL_PATH)
    await _async_ensure_resource(hass)


async def _async_ensure_resource(hass: HomeAssistant) -> None:
    """Add the card to the Lovelace resource list once."""
    try:
        lovelace = hass.data.get(_LOVELACE_DATA)
        resources = getattr(lovelace, "resources", None)
        if resources is None:
            _LOGGER.info(
                "Lovelace 资源未就绪，请手动添加资源：%s（类型：JavaScript 模块）",
                CARD_URL_PATH,
            )
            return
        if not getattr(resources, "loaded", True):
            await resources.async_load()
        for item in resources.async_items():
            if item.get("url") == CARD_URL_PATH:
                return
        await resources.async_create_item(
            {"res_type": "module", "url": CARD_URL_PATH}
        )
        _LOGGER.info("已自动注册 Lovelace 资源：%s", CARD_URL_PATH)
    except Exception as err:  # noqa: BLE001 - YAML mode has no writable collection
        _LOGGER.info(
            "未能自动注册 Lovelace 资源（可手动添加 %s，类型 JavaScript 模块）：%s",
            CARD_URL_PATH,
            err,
        )
