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
    AT_LIFETIME_FALLBACK_SECONDS,
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


class OkpRefreshThrottled(OkpApiError):
    """Raised when a token refresh is skipped because one was just attempted.

    Deliberately *not* an auth failure: nothing about the credentials was
    rejected, the integration simply refuses to hammer the cloud. Treating it
    as an auth failure made the log read "auth failed (5/3)" twice in a row
    and pushed the reauth prompt out for no reason.
    """


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _parse_expire(data: dict[str, Any]) -> int:
    """Read the access-token expiry out of a CoolKit user-info response.

    The field name differs between deployments (``at_expire_at``,
    ``atExpiredTime``, ``expireAt``) and some report milliseconds. Getting this
    wrong is not cosmetic: without a known expiry the integration falls back to
    a fixed refresh interval, and if it refreshes *after* the token died the
    renewal request is rejected - the token in the Authorization header has to
    still be known to the gateway.
    """
    for key in ("at_expire_at", "atExpiredTime", "at_expired_at", "expireAt"):
        raw = data.get(key)
        if not raw:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 10**11:  # milliseconds -> seconds
            value //= 1000
        return value
    return 0


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
        # How the current CoolKit session was last obtained / renewed. Surfaced
        # to the user by the session diagnostic sensor: "rt" means the session
        # renews itself and does not care about the phone app, "okplife" means
        # it still depends on the OKP login token (which the app kicks out).
        self.session_source: str = "none"
        # Last CoolKit refresh-token failure, kept for the diagnostic sensor.
        self.last_rt_error: str | None = None
        # Only warn once per process when okplife hands out at-only credentials.
        self._warned_no_rt: bool = False
        # Set when CoolKit rejected the access token. The token itself is kept
        # (see _mark_at_rejected) - only the "still valid" belief is dropped.
        self.at_rejected: bool = False
        # v1.2.10: field names returned by the last renewal response. The
        # gateway omits the expiry in some deployments, and guessing wrong
        # means renewing too late. Exposed by the diagnostic sensor / service.
        self.last_refresh_fields: list[str] = []
        # True when coolkit_at_expire was inferred locally instead of read
        # from the cloud response.
        self.at_expire_inferred: bool = False
        # How long a freshly issued access token is assumed to live. Updated
        # whenever the cloud actually tells us (see refresh_coolkit_token);
        # otherwise the documented 30-day policy minus a safety margin.
        self.at_lifetime: int = AT_LIFETIME_FALLBACK_SECONDS

    # -- low level helpers ------------------------------------------------

    @property
    def session(self) -> aiohttp.ClientSession:
        """The shared aiohttp session (the realtime socket uses it too)."""
        return self._session

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

    def _mark_at_rejected(self) -> None:
        """Note that CoolKit rejected the access token, without dropping it.

        The value is deliberately kept: the refresh endpoint takes it in the
        Authorization header, so throwing it away is what turned a renewable
        session into one that needed a manual reauth. Only the expiry hint and
        the "valid" flag are cleared.
        """
        self.at_rejected = True
        self.coolkit_at_expire = 0

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
        # Never drop a refresh token we already hold just because this response
        # omits it: some deployments return it only on the first call, and
        # overwriting with None turned the session back into an
        # okplife-dependent one (i.e. one the phone app can kick out).
        new_rt = data.get("rt")
        if new_rt:
            self.coolkit_rt = new_rt
            self.last_rt_error = None
        self.coolkit_apikey = data.get("apikey") or self.coolkit_apikey
        self.coolkit_region = data.get("region") or self.coolkit_region
        self.coolkit_at_expire = _parse_expire(data)
        self.last_refresh_fields = sorted(str(k) for k in data.keys())
        self.at_expire_inferred = not bool(self.coolkit_at_expire)
        if self.coolkit_at_expire:
            # Remember the real lifetime for renewals that omit the field.
            self.at_lifetime = max(600, self.coolkit_at_expire - int(time.time()))
        self.coolkit_refreshed_at = time.time()
        self.at_rejected = False
        self.session_source = "okplife"
        if not self.coolkit_rt:
            if not self._warned_no_rt:
                self._warned_no_rt = True
                _LOGGER.warning(
                    "OKP get-user-info returned no CoolKit refresh token; the "
                    "session will keep depending on the OKP login token, which "
                    "the phone app kicks out on every login. Re-authenticate "
                    "once while the app is closed to capture one"
                )

    async def refresh_coolkit_by_rt(self) -> bool:
        """Renew the CoolKit session with the CoolKit refresh token.

        This is the only renewal path that does not depend on the OKP access
        token: the OKP login token lives for a few hours, okplife exposes no
        refresh route for it, and every login into the phone app invalidates
        it. The CoolKit refresh token survives all of that (and HA restarts,
        because it is persisted in the config entry), so renewing with it is
        what keeps the integration and the phone app out of each other's way.

        Returns True when a new token was obtained, False when there is no
        refresh token to use (caller should fall back to okplife).
        """
        if not self.coolkit_rt:
            self.last_rt_error = "no refresh token stored in the config entry"
            return False
        self._last_refresh_try = time.time()
        # The gateway requires an Authorization header here, of the form
        # "Bearer <hex>"; without it every call fails with
        # 400 "authorization" is required. That is why renewal never worked
        # before: the error was swallowed at debug level and the integration
        # silently fell back to the okplife route every single time. Which hex
        # value the gateway accepts is undocumented - the access token is the
        # natural choice, but it is usually the thing that expired, so the
        # refresh token is tried as a second candidate.
        candidates: list[tuple[str, str]] = []
        if self.coolkit_at:
            candidates.append(("Bearer " + self.coolkit_at, "access token"))
        candidates.append(("Bearer " + self.coolkit_rt, "refresh token"))

        last_error: str | None = None
        for auth_value, label in candidates:
            headers = {
                "authorization": auth_value,
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

            error = body.get("error")
            if not error:
                data = body.get("data") or {}
                at = data.get("at")
                if not at:
                    raise OkpApiError("coolkit refresh returned no at")
                self.coolkit_at = at
                self.coolkit_rt = data.get("rt") or self.coolkit_rt
                self.at_rejected = False
                self.last_refresh_fields = sorted(str(k) for k in data.keys())
                expire = _parse_expire(data)
                now = time.time()
                if expire:
                    self.coolkit_at_expire = expire
                    self.at_expire_inferred = False
                    # Learn the real lifetime so later renewals that omit the
                    # field are still timed correctly.
                    self.at_lifetime = max(600, expire - int(now))
                else:
                    # v1.2.11: this gateway answers with just at/rt and no
                    # expiry. The documented policy is a 30-day access token,
                    # so assume the known lifetime (25 days by default) rather
                    # than the 1-hour placeholder of v1.2.10 - that placeholder
                    # made every HA downtime longer than an hour need a manual
                    # reauthentication, while this one tolerates 25 days.
                    self.coolkit_at_expire = int(now) + self.at_lifetime
                    self.at_expire_inferred = True
                self.coolkit_refreshed_at = time.time()
                self.session_source = "rt"
                self.last_rt_error = None
                _LOGGER.debug(
                    "OKP CoolKit token renewed via rt using the %s (expires %s)",
                    label,
                    self.coolkit_at_expire or "unknown",
                )
                return True

            msg = body.get("msg") or body.get("message") or "unknown"
            last_error = f"{error}: {msg}"
            if error in (400, 401):
                # The header was rejected or the token in it is unknown. That
                # says nothing about the refresh token itself, so try the next
                # candidate before drawing a conclusion.
                _LOGGER.debug(
                    "OKP refresh with the %s rejected (%s); trying next candidate",
                    label,
                    last_error,
                )
                continue
            break

        self.last_rt_error = last_error
        if last_error and last_error.startswith(("402", "403")):
            # The cloud rejected the refresh token itself; stop retrying with
            # it. A 400/401 is kept (see above) - discarding the token over a
            # header problem would permanently give up the only session that
            # does not depend on the phone app.
            self.coolkit_rt = None
        raise OkpApiError(f"coolkit refresh failed: {last_error}")

    async def ensure_coolkit_token(self) -> None:
        # Refresh when: no token, token within 5 min of expiry, or no expiry
        # metadata returned (some endpoints omit at_expire_at) and the token
        # is older than 12 hours. This is a safety net so a stale token never
        # keeps polling 401 forever.
        # No known expiry: refresh hourly. The renewal endpoint only accepts an
        # access token the gateway still knows, so waiting 12 hours (the old
        # value) risked refreshing only after the token had already died, which
        # turns a renewable session into a reauthentication prompt.
        stale = (
            not self.coolkit_refreshed_at
            or time.time() - self.coolkit_refreshed_at > 3600
        )
        if self.coolkit_at and not self.at_rejected and not (
            (self.coolkit_at_expire and time.time() >= self.coolkit_at_expire - 300)
            or (not self.coolkit_at_expire and stale)
        ):
            return
        # After the token was cleared (401/402/403) or is missing, a refresh
        # may fail transiently; throttle repeated attempts so a down OKP
        # network cannot cause a refresh storm against the cloud.
        if time.time() - self._last_refresh_try < REFRESH_MIN_INTERVAL:
            raise OkpRefreshThrottled("coolkit token refresh throttled (recent attempt)")
        # 1) Preferred: renew the CoolKit session with its own refresh token.
        #    Independent of the OKP access token, so it keeps working after
        #    the OKP token expires.
        if self.coolkit_rt:
            try:
                if await self.refresh_coolkit_by_rt():
                    return
            except OkpAuthError as err:
                # The refresh token itself was rejected - the session is back
                # to depending on the OKP login token, which the phone app
                # kicks out. Worth a warning, it explains the next 4001.
                _LOGGER.warning(
                    "OKP CoolKit refresh token rejected (%s); session falls "
                    "back to the OKP login token",
                    err,
                )
            except OkpApiError as err:
                _LOGGER.debug("OKP rt refresh failed, falling back to okplife: %s", err)
        # 2) Fallback: ask okplife for a brand new CoolKit token. Needs a live
        #    OKP access token; raises OkpAuthError (-> reauth) when it is gone.
        await self.refresh_coolkit_token()

    @property
    def session_state(self) -> str:
        """Describe the session, for the diagnostic sensor.

        ``rt``      - a usable access token plus a refresh token: the session
                      renews itself and app logins no longer matter.
        ``okplife`` - only an access token, renewed through the OKP login
                      token, which every app login invalidates.
        ``stale``   - the access token is gone or was rejected. The refresh
                      token cannot get a new one on its own, because the
                      renewal endpoint requires a live access token in the
                      Authorization header - one reauthentication is needed.
        ``expired`` - no token at all.
        """
        if not self.coolkit_at and not self.coolkit_rt:
            return "expired"
        if self.at_rejected or not self.coolkit_at:
            return "stale" if self.coolkit_rt else "expired"
        return "rt" if self.coolkit_rt else "okplife"

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
                self._mark_at_rejected()
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
                self._mark_at_rejected()
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
                self._mark_at_rejected()
                raise OkpAuthError(f"coolkit {error}: {msg}")
            raise OkpApiError(f"coolkit error {error}: {msg}")
        return body

    async def get_cleaning_history(self, device_id: str, num: int = 3) -> list[dict]:
        """Return recent cleaning runs (each with a cleaningId).

        ``from`` is an upper-bound cursor in **microseconds**. The v3.4.0 app
        sends a 16-digit value (e.g. 1793496616513000) and gets the newest
        ``num`` runs; older builds here passed milliseconds (13 digits), which
        the server interprets differently and answers with a much shorter -
        and possibly stale - list. Match the app so the newest run is what
        comes back.
        """
        now_us = int(time.time() * 1_000_000)
        body = await self._ck_get(
            f"{CK_BASE}{CK_ENDPOINT_SWEEP_HISTORY}"
            f"?deviceid={device_id}&from={now_us}&num={num}"
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
                self._mark_at_rejected()
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
