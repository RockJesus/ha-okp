"""OKP cloud API client (async, aiohttp)."""
from __future__ import annotations

import hashlib
import logging
import time
import uuid
from typing import Any

import aiohttp

from .const import (
    API_BASE,
    CK_APP_ID,
    CK_BASE,
    CK_DOMAIN,
    CK_ENDPOINT_OTA_QUERY,
    CK_ENDPOINT_SWEEP_HISTORY,
    CK_ENDPOINT_SWEEP_MAP,
    CK_ENDPOINT_THING,
    CK_ENDPOINT_THING_UPDATE,
    CK_ENDPOINT_USER_REFRESH,
    ENDPOINT_CK_USER_INFO,
    ENDPOINT_DEVICE_DETAIL,
    ENDPOINT_DEVICE_LIST,
    ENDPOINT_HOME_LIST,
    ENDPOINT_LOGIN,
    OKP_HEADERS,
    REFRESH_MIN_INTERVAL,
    SIGN_CLIENT_ID,
    SIGN_KEY,
)

_LOGGER = logging.getLogger(__name__)


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
        # Cooldown for refresh *attempts*: after a failed refresh (network or
        # auth), do not retry the OKP refresh endpoint more often than this
        # to stay below the cloud's risk-control radar.
        self._last_refresh_try: float = 0.0

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

    async def get_homes(self) -> list[dict]:
        """Return every home under the account (v1.2.0: multi-home scan)."""
        body = await self._request(f"{API_BASE}{ENDPOINT_HOME_LIST}", None, auth=True)
        homes = body.get("data")
        if isinstance(homes, dict):
            homes = homes.get("list") or []
        return homes or []

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
        self._last_refresh_try = time.time()
        # v1.2.0: the app obtains CoolKit credentials from
        # GET /v1/coolkit/get-user-info (same signed headers as every other
        # okplife call). The old refresh-access-token endpoint is no longer
        # called by the v3.4.0 app and may be retired server-side.
        body = await self._get(f"{API_BASE}{ENDPOINT_CK_USER_INFO}", auth=True)
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

    async def refresh_coolkit_by_rt(self) -> bool:
        """Renew the CoolKit session with the CoolKit refresh token.

        CoolKit has its own renewal endpoint, and it is the only one that does
        not depend on the OKP access token: the OKP login token lives for a
        few hours and okplife exposes no refresh route for it, so an
        integration that only knows how to ask okplife for a new CoolKit token
        goes dead every few hours and needs the user to type the password
        again. The refresh token survives that (and HA restarts, because it is
        persisted in the config entry).

        Returns True when a new token was obtained, False when there is no
        refresh token to use (caller should fall back to okplife).
        """
        if not self.coolkit_rt:
            return False
        self._last_refresh_try = time.time()
        headers = {
            "x-ck-appid": CK_APP_ID,
            "domain-name": CK_DOMAIN,
            "content-type": "application/json",
        }
        try:
            async with self._session.post(
                f"{CK_BASE}{CK_ENDPOINT_USER_REFRESH}",
                json={"rt": self.coolkit_rt},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                body = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise OkpApiError(f"coolkit refresh network error: {err}") from err
        except ValueError as err:
            raise OkpApiError(f"bad response from coolkit refresh: {err}") from err
        if body.get("error"):
            error = body.get("error")
            msg = body.get("msg") or body.get("message") or "unknown"
            if error in (401, 402, 403):
                # Refresh token rejected: drop it so we stop retrying with it
                # and let the caller fall back to the okplife route.
                self.coolkit_rt = None
                raise OkpAuthError(f"coolkit refresh {error}: {msg}")
            raise OkpApiError(f"coolkit refresh error {error}: {msg}")
        data = body.get("data") or {}
        at = data.get("at")
        if not at:
            raise OkpApiError("coolkit refresh returned no at")
        self.coolkit_at = at
        self.coolkit_rt = data.get("rt") or self.coolkit_rt
        expire = data.get("atExpiredTime") or data.get("at_expire_at")
        if expire:
            try:
                expire = int(expire)
            except (TypeError, ValueError):
                expire = 0
            if expire > 10**11:  # milliseconds -> seconds
                expire //= 1000
            if expire:
                self.coolkit_at_expire = expire
        self.coolkit_refreshed_at = time.time()
        _LOGGER.debug(
            "OKP CoolKit token renewed via rt (expires %s)",
            self.coolkit_at_expire or "unknown",
        )
        return True

    async def ensure_coolkit_token(self) -> None:
        # Refresh when: no token, token within 5 min of expiry, or no expiry
        # metadata returned (some endpoints omit at_expire_at) and the token
        # is older than 12 hours. This is a safety net so a stale token never
        # keeps polling 401 forever.
        stale = (
            not self.coolkit_refreshed_at
            or time.time() - self.coolkit_refreshed_at > 12 * 3600
        )
        if self.coolkit_at and not (
            (self.coolkit_at_expire and time.time() >= self.coolkit_at_expire - 300)
            or (not self.coolkit_at_expire and stale)
        ):
            return
        # After the token was cleared (401/402/403) or is missing, a refresh
        # may fail transiently; throttle repeated attempts so a down OKP
        # network cannot cause a refresh storm against the cloud.
        if time.time() - self._last_refresh_try < REFRESH_MIN_INTERVAL:
            raise OkpApiError("coolkit token refresh throttled (recent attempt)")
        # 1) Preferred: renew the CoolKit session with its own refresh token.
        #    Independent of the OKP access token, so it keeps working after
        #    the OKP token expires.
        if self.coolkit_rt:
            try:
                if await self.refresh_coolkit_by_rt():
                    return
            except OkpApiError as err:
                _LOGGER.debug("OKP rt refresh failed, falling back to okplife: %s", err)
        # 2) Fallback: ask okplife for a brand new CoolKit token. Needs a live
        #    OKP access token; raises OkpAuthError (-> reauth) when it is gone.
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
        # CoolKit v2 set-status schema: {"type":1,"id":<deviceid>,"params":{}}.
        # type 1 = single device (2 = group). The old {"thing": {...}} wrapper
        # was rejected by the gateway before the body was even parsed.
        payload = {"type": 1, "id": device_id, "params": params}
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
            # Only 401/402 mean "token invalid" -> clear it so the next poll
            # refreshes. 403 is a header/permission problem (e.g. wrong
            # x-ck-appid or a non-existent route) and must NOT wipe a token
            # that still works for reads.
            if error in (401, 402):
                self.coolkit_at = None
                self.coolkit_at_expire = 0
                raise OkpAuthError(f"coolkit update {error}: {msg}")
            if error == 4002:
                raise OkpApiError(f"coolkit update 4002 (设备离线或指令无效): {msg}")
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
        """Return recent cleaning runs (each with a cleaningId).

        The `from` parameter is a millisecond epoch (13 digits) exactly as the
        app sends it (e.g. 1785978545000). Older builds passed microseconds
        (16 digits), which the server does not accept as "now", causing the
        history/map endpoints to return empty data.
        """
        now_ms = int(time.time() * 1000)
        body = await self._ck_get(
            f"{CK_BASE}{CK_ENDPOINT_SWEEP_HISTORY}"
            f"?deviceid={device_id}&from={now_ms}&num={num}"
        )
        return (body.get("data") or {}).get("histories") or []

    async def query_ota(self, device_id: str, model: str | None, version: str | None) -> dict:
        """Ask the CoolKit cloud whether a firmware update is available.

        Returns the otaInfoList dict (usually {"otaInfoList": [...]}).
        """
        await self.ensure_coolkit_token()
        headers = {
            "authorization": f"Bearer {self.coolkit_at}",
            "x-ck-appid": CK_APP_ID,
            "domain-name": CK_DOMAIN,
            "content-type": "application/json",
        }
        payload = {
            "deviceInfoList": [
                {
                    "deviceid": device_id,
                    "model": model or "",
                    "version": version or "",
                }
            ]
        }
        try:
            async with self._session.post(
                f"{CK_BASE}{CK_ENDPOINT_OTA_QUERY}",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                body = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise OkpApiError(f"coolkit ota network error: {err}") from err
        if body.get("error"):
            error = body.get("error")
            msg = body.get("msg") or body.get("message") or "unknown"
            if error in (401, 402, 403):
                self.coolkit_at = None
                self.coolkit_at_expire = 0
                raise OkpAuthError(f"coolkit ota {error}: {msg}")
            raise OkpApiError(f"coolkit ota error {error}: {msg}")
        return (body.get("data") or {}).get("otaInfoList") or []

    async def get_cleaning_map(self, device_id: str, cleaning_id: str) -> list[str]:
        """Return mapPaths for one cleaning run (grid points as strings)."""
        body = await self._ck_get(
            f"{CK_BASE}{CK_ENDPOINT_SWEEP_MAP}"
            f"?deviceid={device_id}&id={cleaning_id}"
        )
        return (body.get("data") or {}).get("mapPaths") or []
