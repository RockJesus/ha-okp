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
    CK_ENDPOINT_SWEEP_HISTORY,
    CK_ENDPOINT_SWEEP_MAP,
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
        self.coolkit_refreshed_at: float = 0.0

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
            # 4001 = "请先登录" (access token expired/invalid) -> treat as auth
            # error so the coordinator re-logins instead of getting stuck.
            if code in (4001, 40003, 401, 403):
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
            code = body.get("status")
            msg = body.get("message") or body.get("msg") or "unknown"
            if code in (4001, 40003, 401, 403):
                raise OkpAuthError(f"{code}: {msg}")
            raise OkpApiError(f"{code}: {msg}")
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
        self.user_id = data.get("user_id")
        if not self.access_token:
            raise OkpAuthError("login succeeded but no access_token returned")
        if self.user_id is not None:
            self.user_id = str(self.user_id)
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
        self.coolkit_refreshed_at = time.time()

    async def ensure_coolkit_token(self) -> None:
        # Refresh when: no token, token within 5 min of expiry, or no expiry
        # metadata returned (some endpoints omit at_expire_at) and the token
        # is older than 12 hours. This is a safety net so a stale token never
        # keeps polling 401 forever.
        stale = (
            not getattr(self, "coolkit_refreshed_at", 0)
            or time.time() - self.coolkit_refreshed_at > 12 * 3600
        )
        if not self.coolkit_at or (
            self.coolkit_at_expire and time.time() >= self.coolkit_at_expire - 300
        ) or (not self.coolkit_at_expire and stale):
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
            error = body.get("error")
            msg = body.get("msg") or body.get("message") or "unknown"
            # A 401/402/403 CoolKit response means the access token is stale
            # or invalid. Clear it so the next call refreshes, and surface it
            # as an auth error so the coordinator can re-login automatically.
            if error in (401, 402, 403):
                self.coolkit_at = None
                self.coolkit_at_expire = 0
                raise OkpAuthError(f"coolkit {error}: {msg}")
            raise OkpApiError(f"coolkit error {error}: {msg}")
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
            error = body.get("error")
            msg = body.get("msg") or body.get("message") or "unknown"
            if error in (401, 402, 403):
                self.coolkit_at = None
                self.coolkit_at_expire = 0
                raise OkpAuthError(f"coolkit update {error}: {msg}")
            raise OkpApiError(f"coolkit update error {error}: {msg}")

    # -- sweep map ----------------------------------------------------------

    async def _ck_get(self, url: str) -> dict:
        """CoolKit GET with bearer auth (map/history endpoints)."""
        await self.ensure_coolkit_token()
        headers = {
            "authorization": f"Bearer {self.coolkit_at}",
            "x-ck-appid": CK_APP_ID,
            "domain-name": CK_DOMAIN,
        }
        try:
            async with self._session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                body = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise OkpApiError(f"coolkit network error: {err}") from err
        if body.get("error"):
            error = body.get("error")
            msg = body.get("msg") or body.get("message") or "unknown"
            # Map endpoints return 405 (NoSuchKey) while the map for a
            # cleaning run is not ready yet - not an auth problem.
            if error in (401, 402, 403):
                self.coolkit_at = None
                self.coolkit_at_expire = 0
                raise OkpAuthError(f"coolkit {error}: {msg}")
            raise OkpApiError(f"coolkit error {error}: {msg}")
        return body

    async def get_cleaning_history(self, device_id: str, num: int = 3) -> list[dict]:
        """Return recent cleaning runs (each with a cleaningId)."""
        now_us = int(time.time() * 1000000)
        body = await self._ck_get(
            f"{CK_BASE}{CK_ENDPOINT_SWEEP_HISTORY}"
            f"?deviceid={device_id}&from={now_us}&num={num}"
        )
        return (body.get("data") or {}).get("histories") or []

    async def get_cleaning_map(self, device_id: str, cleaning_id: str) -> list[str]:
        """Return mapPaths for one cleaning run (grid points as strings)."""
        body = await self._ck_get(
            f"{CK_BASE}{CK_ENDPOINT_SWEEP_MAP}"
            f"?deviceid={device_id}&id={cleaning_id}"
        )
        return (body.get("data") or {}).get("mapPaths") or []
