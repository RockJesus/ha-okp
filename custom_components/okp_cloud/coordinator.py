"""Coordinator for the OKP Cloud vacuum integration."""
from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import OkpApi, OkpApiError, OkpAuthError, OkpRefreshThrottled
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAP_CHECK_SECONDS,
    MAP_HISTORY_NUM,
    MAP_REFRESH_MINUTES,
    OTA_CHECK_SECONDS,
    REAUTH_AFTER_FAILURES,
    RELOGIN_COOLDOWN_SECONDS,
)
from .map_render import parse_map_paths, render_map_png

_LOGGER = logging.getLogger(__name__)


class OkpCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch OKP / CoolKit device state on a schedule."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: OkpApi,
        device_id: str,
        entry_id: str | None = None,
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
        # Owning config entry: used to raise the reauth prompt on the right
        # entry when the account has more than one (multi-home / multi-robot).
        self.entry_id = entry_id
        self.account = account
        self.password = password
        self.last_error: str | None = None
        # Sweep map cache: PNG bytes + the cleaning run it belongs to.
        self.map_image: bytes | None = None
        self.map_cleaning_id: str | None = None
        self.map_updated_at: float = 0.0
        self.map_error: str | None = None
        self._map_check_ts: float = 0.0
        # The map-id set currently being probed, so the "did the newest run
        # change?" check does not re-fetch the same failing id every cycle.
        self._map_candidate_key: str | None = None
        # Latest cleaning run from the history endpoint (cleaningId + opsTime
        # + cleaningLogs); backs the "last cleaning time" sensor.
        self.latest_history: dict | None = None
        # Firmware update availability from /v2/device/ota/query (low freq).
        self.ota_available: str | None = None
        self._ota_check_ts: float = 0.0
        self._next_retry_at: float = 0.0
        # Whether a reauth prompt has already been requested for this load.
        self._reauth_requested = False
        # Consecutive failed poll cycles caused by authentication. The reauth
        # prompt only fires after REAUTH_AFTER_FAILURES of them, so a single
        # transient 4001 no longer pops a "re-auth required" banner.
        self._auth_failures = 0
        # Last api.coolkit_refreshed_at value already written to the entry.
        self._token_persist_mark = api.coolkit_refreshed_at
        # Last auth error already logged, so a persistent failure writes one
        # line instead of one every poll cycle.
        self._last_auth_log: str | None = None

    async def _maybe_trigger_reauth(self, err: OkpApiError | OkpAuthError) -> None:
        """Ask Home Assistant to start the reauth flow (user enters password).

        This is a standard HA reauth prompt — the integration never calls the
        password login endpoint by itself, so it can't kick the phone app
        session. Triggered at most once per coordinator load.
        """
        if self._reauth_requested:
            return
        self._reauth_requested = True
        try:
            entry = (
                self.hass.config_entries.async_get_entry(self.entry_id)
                if self.entry_id
                else None
            )
            if entry is None:
                entry = next(
                    (
                        e
                        for e in self.hass.config_entries.async_entries(DOMAIN)
                        if not e.disabled_by
                    ),
                    None,
                )
            if entry:
                started = entry.async_start_reauth(self.hass)
                # async def on recent HA, sync no-op on older ones — await only
                # when it actually returns an awaitable.
                if hasattr(started, "__await__"):
                    await started
                _LOGGER.warning("OKP reauth flow started: %s", err)
        except Exception as exc:  # noqa: BLE001 - reauth is best-effort
            _LOGGER.warning("OKP could not start reauth flow: %s", exc)

    def timers(self) -> list[dict[str, Any]]:
        """Device-side schedules (the ``timers`` dp), or an empty list."""
        params = (self.data or {}).get("params") or {}
        timers = params.get("timers")
        return timers if isinstance(timers, list) else []

    async def async_set_timer_enabled(self, mid: str, enabled: bool) -> bool:
        """Enable/disable one schedule and write the whole array back.

        The cloud has no per-schedule endpoint: the app rewrites the complete
        ``timers`` dp with one entry's ``enabled`` flag flipped, and the robot
        replaces its list with what it receives. That makes a stale read
        dangerous - it would resurrect deleted schedules - so the list is
        re-read from the cloud right before the write, and the result is
        verified against it afterwards.
        """
        # 1. Fresh read: never write a list we read minutes ago.
        await self.async_refresh()
        timers = self.timers()
        if not timers:
            raise OkpApiError("device reports no schedules")

        target = None
        for timer in timers:
            if str(timer.get("mId")) == str(mid):
                target = timer
                break
        if target is None:
            known = ", ".join(str(t.get("mId")) for t in timers)
            raise OkpApiError(f"no schedule with mId {mid} (known: {known})")

        original = {"enabled": target.get("enabled")}
        wanted = 1 if enabled else 0
        if int(target.get("enabled") or 0) == wanted:
            _LOGGER.debug("OKP schedule %s already enabled=%s", mid, wanted)
            return False

        payload = []
        for timer in timers:
            entry = dict(timer)
            if str(entry.get("mId")) == str(mid):
                entry["enabled"] = wanted
            payload.append(entry)

        await self.api.set_thing_params(self.device_id, {"timers": payload})
        await self.async_refresh()

        # 3. Verify: same number of schedules, only the target flag changed.
        after = self.timers()
        if len(after) != len(timers):
            raise OkpApiError(
                f"schedule list changed unexpectedly ({len(timers)} -> {len(after)})"
            )
        for timer in after:
            if str(timer.get("mId")) == str(mid):
                if int(timer.get("enabled") or 0) != wanted:
                    raise OkpApiError(
                        f"schedule {mid} did not switch to enabled={wanted} "
                        f"(still {timer.get('enabled')})"
                    )
                break
        _LOGGER.info(
            "OKP schedule %s enabled %s -> %s",
            mid,
            original["enabled"],
            wanted,
        )
        return True

    def async_persist_tokens(self, force: bool = False) -> None:
        """Public wrapper used by the manual ``refresh_session`` service.

        ``force`` ignores the de-duplication mark so a manually triggered
        renewal is always written to the entry, even when the poll cycle
        already persisted the same tokens.
        """
        if force:
            self._token_persist_mark = None
        self._persist_tokens()

    def _persist_tokens(self) -> None:
        """Write the CoolKit token pair back into the config entry.

        Persisting ``rt`` is what makes the integration survive an OKP access
        token expiry *and* a Home Assistant restart: without it the only way
        to get a new CoolKit token is the okplife route, which needs a live
        (and short-lived) OKP token. Tokens are written only when a refresh
        actually happened, so the entry is not rewritten on every poll.
        """
        api = self.api
        if api.coolkit_refreshed_at == self._token_persist_mark:
            return
        entry = (
            self.hass.config_entries.async_get_entry(self.entry_id)
            if self.entry_id
            else None
        )
        if entry is None:
            return
        new_data = {
            **entry.data,
            "coolkit_at": api.coolkit_at,
            "coolkit_at_expire": api.coolkit_at_expire,
            # v1.2.12: persist how the expiry was obtained and the learned
            # token lifetime, so the diagnostic sensor keeps telling the truth
            # after a restart instead of reporting an inferred value as if the
            # cloud had provided it.
            "coolkit_at_expire_inferred": api.at_expire_inferred,
            "coolkit_at_lifetime": api.at_lifetime,
            "coolkit_rt": api.coolkit_rt,
            "coolkit_apikey": api.coolkit_apikey,
            "coolkit_region": api.coolkit_region,
        }
        self._token_persist_mark = api.coolkit_refreshed_at
        if new_data != entry.data:
            self.hass.config_entries.async_update_entry(entry, data=new_data)
            _LOGGER.debug("OKP CoolKit tokens persisted to the config entry")

    def _map_candidates(self, histories: list[dict]) -> list[str]:
        """Map ids to try, newest run first (see _async_refresh_map).

        The map endpoint is keyed by the *upload* id (the ``endUpload`` /
        ``startUpload`` dp values, e.g. "015c"), not by the ``cleaningId`` of a
        history record (e.g. "0125"). The v3.4.0 capture only ever asked for
        upload ids, while this integration used to send cleaningId - which is
        what produced the "405 NoSuchKey" map errors. History ids are kept as
        a last resort so other firmware builds still work.
        """
        out: list[str] = []
        params = (self.data or {}).get("params") or {}
        for key in ("endUpload", "startUpload"):
            value = params.get(key)
            value = "" if value is None else str(value)
            if value and value not in ("0000", "-") and value not in out:
                out.append(value)
        for record in histories:
            cid = record.get("cleaningId")
            if cid and str(cid) not in out:
                out.append(str(cid))
        return out[:4]

    async def _async_refresh_map(self) -> None:
        """Fetch the newest cleaning run map (low frequency).

        Probes the history endpoint at most every MAP_CHECK_SECONDS; pulls a
        new map when the newest candidate id changes or every
        MAP_REFRESH_MINUTES. Failures are logged and never block the main
        poll cycle.
        """
        now = time.time()
        if now - self._map_check_ts < MAP_CHECK_SECONDS:
            return
        self._map_check_ts = now
        try:
            histories = await self.api.get_cleaning_history(self.device_id, MAP_HISTORY_NUM)
            if histories:
                self.latest_history = histories[0]
            else:
                self.latest_history = None
                self.map_error = "no cleaning history yet"
                return
            candidates = self._map_candidates(histories)
            if not candidates:
                self.map_error = "no map id available yet"
                return
            newest = candidates[0]
            due = newest != self._map_candidate_key or (
                now - self.map_updated_at > MAP_REFRESH_MINUTES * 60
            )
            if not due:
                return
            self._map_candidate_key = newest

            paths: list[str] = []
            used: str | None = None
            last_error: str | None = None
            for map_id in candidates:
                try:
                    found = await self.api.get_cleaning_map(self.device_id, map_id)
                except OkpAuthError:
                    # Real session problem: let the caller handle it.
                    raise
                except OkpApiError as err:
                    # 405 NoSuchKey simply means that run's map is not uploaded
                    # (or already expired); try the next id.
                    last_error = str(err)
                    continue
                if found:
                    paths = found
                    used = map_id
                    break
            if not paths:
                self.map_error = last_error or "no map data for the latest run"
                return

            points = parse_map_paths(paths)
            if not points:
                self.map_error = "map data empty"
                return
            self.map_image = render_map_png(points)
            self.map_cleaning_id = used
            self.map_updated_at = time.time()
            self.map_error = None
            _LOGGER.debug("OKP map updated: %s (%d points)", used, len(points))
        except (OkpApiError, OkpAuthError) as err:
            # Keep the previous image; retry next cycle.
            self.map_error = str(err)
            _LOGGER.warning("OKP map refresh failed: %s", err)

    async def _async_check_ota(self) -> None:
        """Probe firmware-update availability at most once per hour."""
        now = time.time()
        if now - self._ota_check_ts < OTA_CHECK_SECONDS:
            return
        self._ota_check_ts = now
        try:
            item = self.data.get("item") if self.data else None
            params = (item or {}).get("params") or {}
            model = (item or {}).get("productModel") or ""
            fw = params.get("fwVersion") or ""
            info = await self.api.query_ota(self.device_id, model, fw)
            if info and isinstance(info, list) and info[0]:
                self.ota_available = str(
                    info[0].get("version") or info[0].get("targetVersion") or "available"
                )
            else:
                self.ota_available = None
        except (OkpApiError, OkpAuthError) as err:
            _LOGGER.debug("OKP OTA check skipped: %s", err)

    @property
    def auth_failure_count(self) -> int:
        """Consecutive failed poll cycles caused by authentication."""
        return self._auth_failures

    def _log_auth_failure(self, err: Exception) -> None:
        """Log an auth failure once, not once per poll cycle."""
        message = str(err)
        if message == self._last_auth_log:
            _LOGGER.debug("OKP auth still failing: %s", message)
            return
        self._last_auth_log = message
        _LOGGER.warning(
            "OKP auth failed (%d/%d): %s",
            self._auth_failures,
            REAUTH_AFTER_FAILURES,
            message,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            item = await self.api.get_thing_state(self.device_id)
        except OkpRefreshThrottled as err:
            # Purely local rate limiting: we are waiting out
            # REFRESH_MIN_INTERVAL. No credential was rejected, so this must
            # not count as an auth failure (it used to read "auth failed (5/3)"
            # on alternating polls) and it does not deserve a warning.
            self.last_error = str(err)
            raise UpdateFailed(str(err)) from err
        except OkpAuthError as auth_err:
            # CoolKit token expired/rejected: renew it without touching the
            # password login (which would kick the phone app session). Every
            # failed cycle counts, including the ones that only wait out the
            # cooldown — otherwise the "re-authentication required" prompt
            # would take half an hour to show up.
            now = time.time()
            self._auth_failures = min(self._auth_failures + 1, REAUTH_AFTER_FAILURES)
            err: OkpApiError | None = auth_err
            if now >= self._next_retry_at:
                self._next_retry_at = now + RELOGIN_COOLDOWN_SECONDS
                try:
                    # ensure_coolkit_token() prefers the CoolKit refresh token
                    # and only falls back to okplife, so a dead OKP access
                    # token does not necessarily end the session.
                    await self.api.ensure_coolkit_token()
                    item = await self.api.get_thing_state(self.device_id)
                    self._persist_tokens()
                    err = None
                except OkpRefreshThrottled as exc:
                    self.last_error = str(exc)
                    raise UpdateFailed(str(exc)) from exc
                except (OkpApiError, OkpAuthError) as exc:
                    err = exc
            if err is not None:
                self.last_error = str(err)
                self._log_auth_failure(err)
                if self._auth_failures >= REAUTH_AFTER_FAILURES:
                    await self._maybe_trigger_reauth(err)
                raise UpdateFailed(str(err)) from err
        except OkpApiError as err:
            self.last_error = str(err)
            _LOGGER.warning("OKP state fetch failed: %s", err)
            raise UpdateFailed(str(err)) from err
        self.last_error = None
        self._auth_failures = 0
        self._last_auth_log = None
        self._persist_tokens()
        await self._async_refresh_map()
        await self._async_check_ota()
        return {
            "item": item,
            "params": item.get("params") or {},
            "online": bool(item.get("online")),
            "devicekey": item.get("devicekey"),
            "fw_version": (item.get("params") or {}).get("fwVersion"),
            "history": self.latest_history,
            "ota_available": self.ota_available,
        }
