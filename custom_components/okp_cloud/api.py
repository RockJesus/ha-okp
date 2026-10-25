"""OKP cloud API client (async, aiohttp)."""
from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any

import aiohttp

from .const import (
    API_BASE,
    CK_APP_ID,
    CK_BASE,
    CK_DOMAIN,
    CK_ENDPOINT_THING,
    CK_ENDPOINT_THING_UPDATE,
    ENDPOINT_CK_REFRESH,
    ENDPOINT_DEVICE_DETAIL,
    ENDPOINT_DEVICE_LIST,
    ENDPOINT_HOME_LIST,
    ENDPOINT_LOGIN,
    OKP_HEADERS,
    SIGN_CLIENT_ID,
    SIGN_KEY,
)


class OkpApiError(Exception):
    """Raised when the OKP API returns an error."""


class OkpAuthError(OkpApiError):
    """Raised when login / authentication fails."""


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


class OkpApi:
    """Client for the OKP (Lefant/ThingClips) cloud."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self._uuid = uuid.uuid4().hex[:16]
        self.access_token: str | None = None
        self.user_id: str | None = None
        self.coolkit_at: str | None = None
        self.coolkit_rt: str | None = None
        self.coolkit_apikey: str | None = None
        self.coolkit_at_expire: int = 0
        self.coolkit_region: str | None = None

    # -- low level helpers ------------------------------------------------

    def _headers(self, auth: bool = False) -> dict[str, str]:
        ts = str(int(time.time() * 1000))
        sign = _md5(f"client-id={SIGN_CLIENT_ID}&timestamp={ts}&key={SIGN_KEY}")
        headers = {
            **OKP_HEADERS,
            "client-id": SIGN_CLIENT_ID,
            "timestamp": ts,
            "sign": sign,
            "uuid": self._uuid,
            "content-type": "application/x-www-form-urlencoded",
        }
        if auth and self.access_token and self.user_id:
            headers["user-id"] = self.user_id
            headers["access-token"] = self.access_token
        return headers

    async def _request(self, url: str, payload: dict | None, auth: bool = False) -> dict:
        headers = self._headers(auth)
        data = payload or None  # dict -> urlencoded by aiohttp (form content-type)
        try:
            async with self._session.post(
                url, data=data, headers=headers, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                body = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise OkpApiError(f"network error: {err}") from err
        except ValueError as err:
            raise OkpApiError(f"bad response from {url}: {err}") from err
        if isinstance(body, dict) and body.get("status") not in (None, 200):
            code = body.get("status")
            msg = body.get("message") or body.get("msg") or "unknown"
            if code in (40003, 401, 403):
                raise OkpAuthError(f"{code}: {msg}")
            raise OkpApiError(f"{code}: {msg}")
        return body

    async def _get(self, url: str, auth: bool = False) -> dict:
        headers = self._headers(auth)
        try:
            async with self._session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                body = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise OkpApiError(f"network error: {err}") from err
        except ValueError as err:
            raise OkpApiError(f"bad response from {url}: {err}") from err
        if isinstance(body, dict) and body.get("status") not in (None, 200):
            raise OkpApiError(f"{body.get('status')}: {body.get('message') or body.get('msg')}")
        return body

    # -- auth -------------------------------------------------------------

    async def login(self, account: str, password: str) -> dict:
        """Login with password and store tokens. Returns device/user data."""
        body = await self._request(
            f"{API_BASE}{ENDPOINT_LOGIN}",
            {"password": password, "account": account},
        )
        data = body.get("data") or {}
        self.access_token = data.get("access_token")
        self.user_id = str(data.get("user_id"))
        if not self.access_token:
            raise OkpAuthError("login succeeded but no access_token returned")
        return data

    async def get_home_id(self) -> str:
        body = await self._request(f"{API_BASE}{ENDPOINT_HOME_LIST}", None, auth=True)
        homes = body.get("data")
        if isinstance(homes, dict):
            homes = homes.get("list") or []
        if not homes:
            raise OkpApiError("no homes found")
        return str(homes[0].get("home_id") or homes[0].get("id"))

    async def get_devices(self, home_id: str) -> list[dict]:
        body = await self._request(
            f"{API_BASE}{ENDPOINT_DEVICE_LIST}", {"home_id": home_id}, auth=True
        )
        devices = body.get("data")
        if isinstance(devices, dict):
            devices = devices.get("list") or []
        return devices or []

    async def get_device_detail(self, home_id: str, device_id: str) -> dict:
        body = await self._request(
            f"{API_BASE}{ENDPOINT_DEVICE_DETAIL}",
            {"home_id": home_id, "home_device_id": device_id},
            auth=True,
        )
        return body.get("data") or {}

    # -- CoolKit -----------------------------------------------------------

    async def refresh_coolkit_token(self) -> None:
        body = await self._get(f"{API_BASE}{ENDPOINT_CK_REFRESH}", auth=True)
        data = body.get("data") or {}
        at = data.get("at")
        if not at:
            raise OkpApiError("no coolkit at returned")
        self.coolkit_at = at
        self.coolkit_rt = data.get("rt")
        self.coolkit_apikey = data.get("apikey")
        self.coolkit_region = data.get("region")
        expire = data.get("at_expire_at")
        self.coolkit_at_expire = int(expire) if expire else 0

    async def ensure_coolkit_token(self) -> None:
        if not self.coolkit_at or (self.coolkit_at_expire and time.time() >= self.coolkit_at_expire - 300):
            await self.refresh_coolkit_token()

    async def get_thing_state(self, device_id: str) -> dict:
        await self.ensure_coolkit_token()
        headers = {
            "authorization": f"Bearer {self.coolkit_at}",
            "x-ck-appid": CK_APP_ID,
            "domain-name": CK_DOMAIN,
            "content-type": "application/json",
        }
        payload = {"thingList": [{"id": device_id, "itemType": 1}]}
        try:
            async with self._session.post(
                f"{CK_BASE}{CK_ENDPOINT_THING}",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                body = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise OkpApiError(f"coolkit network error: {err}") from err
        if body.get("error"):
            raise OkpApiError(f"coolkit error {body.get('error')}: {body.get('msg')}")
        things = ((body.get("data") or {}).get("thingList") or [])
        if not things:
            raise OkpApiError("coolkit returned no things")
        item = things[0].get("itemData") or {}
        return item

    async def set_thing_params(self, device_id: str, params: dict) -> None:
        await self.ensure_coolkit_token()
        headers = {
            "authorization": f"Bearer {self.coolkit_at}",
            "x-ck-appid": CK_APP_ID,
            "domain-name": CK_DOMAIN,
            "content-type": "application/json",
        }
        payload = {"thing": {"itemType": 1, "id": device_id, "params": params}}
        try:
            async with self._session.post(
                f"{CK_BASE}{CK_ENDPOINT_THING_UPDATE}",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                body = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise OkpApiError(f"coolkit update network error: {err}") from err
        if body.get("error"):
            raise OkpApiError(f"coolkit update error {body.get('error')}: {body.get('msg')}")
