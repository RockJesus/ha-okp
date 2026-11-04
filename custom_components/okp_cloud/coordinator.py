"""Coordinator for the OKP Cloud vacuum integration."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import OkpApi, OkpApiError, OkpAuthError, OkpRefreshThrottled
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAP_CHECK_SECONDS,
    MAP_HISTORY_NUM,
    MAP_REFRESH_MINUTES,
    MOVE_DIRECTIONS,
    MOVE_DP,
    MOVE_HOLD_MAX_SECONDS,
    MOVE_RELEASE_VALUE,
    MOVE_WATCHDOG_GRACE,
    OTA_CHECK_SECONDS,
    PUSH_POLL_GUARD_SECONDS,
    REAUTH_AFTER_FAILURES,
    RELOGIN_COOLDOWN_SECONDS,
    SETUP_RETRY_SECONDS,
    persisted_token_fields,
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
        # v1.4.7: True when the most recent failed cycle failed because of
        # credentials rather than the network. __init__.py reads this to decide
        # whether a failed *first* refresh deserves an immediate reauth prompt.
        self.last_error_was_auth = False
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
        # v1.3.3: realtime socket feeding this coordinator (set by __init__.py).
        self.realtime = None
        # Push bookkeeping, surfaced by the realtime sensor.
        self.push_count = 0
        self.last_push_at: float = 0.0
        self.last_poll_at: float = 0.0
        # When a push last asked for a forced HTTP read (see async_apply_push).
        self._last_push_poll: float = 0.0
        # v1.4.2: manual remote bookkeeping. ``move_value`` is what we last
        # wrote (None = never used), and each press bumps a generation so a
        # stale watchdog cannot release a newer press.
        self.move_value: int | None = None
        self.last_move_at: float | None = None
        self._move_lock = asyncio.Lock()
        self._move_generation = 0
        self._move_watchdog: asyncio.Task | None = None
        # v1.5.1: outcome of the last "did the refresh token survive?" probe
        # (see _async_update_data). Kept in memory only: it describes a single
        # auth failure, and the persisted provenance fields cover the rest.
        self.last_rt_probe_at: float = 0.0
        self.last_rt_probe_result: str | None = None
        # One "release + renew" probe per process: if the refresh token is
        # rejected too, repeating it every cooldown only burns the session.
        self._rt_probe_done: bool = False

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

    async def async_trigger_reauth(self, err: BaseException) -> None:
        """Public entry point for the reauth prompt (used by setup)."""
        await self._maybe_trigger_reauth(err)  # type: ignore[arg-type]

    async def async_setup_retry_loop(self, delay: float = SETUP_RETRY_SECONDS) -> None:
        """Keep polling after a failed first refresh.

        ``async_config_entry_first_refresh()`` raises instead of scheduling the
        next interval, so a failed first cycle used to stop the poll loop
        entirely: ``last_poll_at`` froze, ``auth_failures`` never left 1, the
        reauth prompt never appeared and every entity kept its last value
        forever. Retry until a cycle gets through, after which the coordinator
        schedules itself again. Cancelled on entry unload (see __init__.py).
        """
        while True:
            await asyncio.sleep(delay)
            try:
                await self.async_refresh()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - async_refresh already logs it
                pass
            if self.last_update_success:
                _LOGGER.debug("OKP poll loop recovered after a failed first refresh")
                return

    def async_schedule_refresh(self, delays: tuple[float, ...] = (4.0, 12.0)) -> None:
        """Re-read device state shortly after a control write.

        The cloud echoes a device change with a few seconds of latency, so an
        immediate refresh usually reads the *old* value back and the entity
        then looks stuck until the next 180 s poll. Kick a couple of follow-up
        reads instead: the first lands right after the device applies the
        change, the second catches a slower echo.
        """
        async def _later(seconds: float) -> None:
            await asyncio.sleep(seconds)
            await self.async_request_refresh()

        for delay in delays:
            self.hass.async_create_task(_later(delay))

    @callback
    def async_apply_push(self, params: dict[str, Any]) -> None:
        """Merge a device-pushed dp set and notify entities immediately.

        The socket carries either what changed (``{"dp31": true}``) or a full
        snapshot (every dp after a state transition), so the incoming keys are
        merged over the last HTTP read instead of replacing it. No cloud
        request is made - this path exists to avoid polling - and the 180 s
        poll still reconciles anything the socket missed while it was down.
        """
        if not isinstance(params, dict) or not params or not self.data:
            return
        item = dict(self.data.get("item") or {})
        merged = dict(item.get("params") or {})
        merged.update(params)
        item["params"] = merged
        new_data = dict(self.data)
        new_data["item"] = item
        new_data["params"] = merged
        if "fwVersion" in merged:
            new_data["fw_version"] = merged["fwVersion"]
        # A push can only come from a device the cloud is talking to.
        new_data["online"] = True

        self.push_count += 1
        self.last_push_at = time.time()
        if "endUpload" in params:
            # The run's map is (about to be) uploaded; let the next poll probe
            # for it without waiting out the 5-minute map throttle.
            self._map_check_ts = 0.0

        # async_set_updated_data() marks the cycle healthy and reschedules the
        # poll - which is what we want, except that a robot pushing every few
        # seconds would then never be polled again. Force a real HTTP read at
        # least every PUSH_POLL_GUARD_SECONDS so the token, the map and the OTA
        # probe keep running.
        self.async_set_updated_data(new_data)
        now = time.time()
        if (
            now - self.last_poll_at > PUSH_POLL_GUARD_SECONDS
            and now - self._last_push_poll > PUSH_POLL_GUARD_SECONDS / 2
        ):
            self._last_push_poll = now
            self.hass.async_create_task(self.async_request_refresh())

    @callback
    def async_apply_online(self, online: bool) -> None:
        """Apply a cloud-side device online/offline notification.

        The CoolKit socket delivers ``{"action":"sysmsg","params":{"online":..}}``
        the moment a device connects to or disconnects from the cloud. Without
        it the offline transition is only noticed by the next HTTP poll (up to
        180 s later). The entities themselves deliberately stay available and
        keep their last values - this only flips the reported online flag, so
        the connection sensor and vacuum attributes react immediately. The
        next HTTP poll reconciles anything the socket missed.
        """
        if not self.data:
            return
        new_data = dict(self.data)
        new_data["online"] = bool(online)
        item = dict(new_data.get("item") or {})
        item["online"] = bool(online)
        new_data["item"] = item
        self.async_set_updated_data(new_data)

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

    # -- manual remote (v1.4.2) -------------------------------------------

    async def async_move(self, value: int, duration: float) -> dict[str, Any]:
        """Drive the robot in one direction for ``duration`` seconds.

        The app's joystick works as press/release: it writes ``{"move": N}``
        when a direction button goes down and ``{"move": 4}`` when it comes up.
        A duration of 0 means "hold until the caller releases it" — that is what
        a draggable joystick card needs — and a watchdog releases it anyway
        after ``MOVE_HOLD_MAX_SECONDS`` so a closed card or a killed script
        cannot leave the robot driving across the room.

        Returns a small report instead of raising on a partial failure: the
        press may succeed and the release fail, which is exactly the case the
        caller must know about.
        """
        if value == MOVE_RELEASE_VALUE:
            return await self.async_release_move()

        # Serialise presses: two overlapping service calls would otherwise
        # interleave and leave the robot moving with no pending release.
        async with self._move_lock:
            await self.api.set_thing_params(self.device_id, {MOVE_DP: value})
            self.move_value = value
            self.last_move_at = time.time()
            self._move_generation += 1
            generation = self._move_generation

        if duration <= 0:
            self._start_move_watchdog(generation)
            return {"move": value, "duration": 0, "released": False}

        try:
            await asyncio.sleep(duration)
        finally:
            # Release even when the service call was cancelled: a cancelled
            # caller must not leave the robot rolling. Shielded because a
            # cancellation would otherwise abort the request mid-flight.
            release = asyncio.shield(self.async_release_move(generation=generation))
            try:
                await release
            except asyncio.CancelledError:
                _LOGGER.debug("OKP move release continued after cancellation")
        return {"move": value, "duration": duration, "released": True}

    async def async_release_move(self, generation: int | None = None) -> dict[str, Any]:
        """Send the "button released" dp (idempotent)."""
        if generation is not None and generation != self._move_generation:
            # A newer press already superseded this one; releasing now would
            # stop the robot the user just asked to move.
            return {"released": False, "superseded": True}
        async with self._move_lock:
            await self.api.set_thing_params(
                self.device_id, {MOVE_DP: MOVE_RELEASE_VALUE}
            )
            self.move_value = MOVE_RELEASE_VALUE
            self.last_move_at = time.time()
        # Entity attributes are a snapshot of the last write, so an automatic
        # release would otherwise stay invisible until the next poll.
        self.async_schedule_refresh((1.5,))
        return {"released": True}

    def _start_move_watchdog(self, generation: int) -> None:
        """Release a held direction if nobody does it for us."""
        self._cancel_move_watchdog()

        async def _watch() -> None:
            await asyncio.sleep(MOVE_HOLD_MAX_SECONDS + MOVE_WATCHDOG_GRACE)
            if generation != self._move_generation:
                return
            if self.move_value in (None, MOVE_RELEASE_VALUE):
                return
            _LOGGER.warning(
                "OKP manual move still held after %ss; releasing automatically",
                MOVE_HOLD_MAX_SECONDS,
            )
            try:
                await self.async_release_move()
            except (OkpApiError, OkpAuthError) as err:
                _LOGGER.warning("OKP could not release the manual move: %s", err)

        self._move_watchdog = self.hass.async_create_task(_watch())

    def _cancel_move_watchdog(self) -> None:
        task = self._move_watchdog
        self._move_watchdog = None
        if task is not None and not task.done():
            task.cancel()

    def move_state(self) -> dict[str, Any]:
        """What the last manual-remote command was, for the vacuum attributes.

        ``move`` is a command dp: the robot executes it but never reports it
        back (the v3.4.0 capture only ever shows app-origin frames for it), so
        this is the *only* way to see what the integration actually sent.
        Handy for verifying the direction mapping: press "前进" and compare
        ``value`` with what the robot did.
        """
        value = self.move_value
        names = {v: k for k, v in MOVE_DIRECTIONS.items()}
        return {
            "value": value,
            "direction": "released" if value == MOVE_RELEASE_VALUE else names.get(value),
            "at": self.last_move_at,
        }

    async def async_shutdown_move(self) -> None:
        """Release a held direction and stop the watchdog (entry unload)."""
        self._cancel_move_watchdog()
        if self.move_value not in (None, MOVE_RELEASE_VALUE):
            try:
                await self.async_release_move()
            except (OkpApiError, OkpAuthError) as err:
                _LOGGER.debug("OKP move release on unload failed: %s", err)

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
        new_data = {**entry.data, **persisted_token_fields(api)}
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

            # v1.6.7: parse + render are pure CPU work (cell loop + zlib
            # over the whole RGB buffer). Run both in the executor so a map
            # render never blocks the event loop / other integrations.
            points = await self.hass.async_add_executor_job(parse_map_paths, paths)
            if not points:
                self.map_error = "map data empty"
                return
            self.map_image = await self.hass.async_add_executor_job(
                render_map_png, points
            )
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
        self.last_poll_at = time.time()
        try:
            item = await self.api.get_thing_state(self.device_id)
        except OkpRefreshThrottled as err:
            # Purely local rate limiting: we are waiting out
            # REFRESH_MIN_INTERVAL. No credential was rejected, so this must
            # not count as an auth failure (it used to read "auth failed (5/3)"
            # on alternating polls) and it does not deserve a warning.
            self.last_error = str(err)
            self.last_error_was_auth = False
            raise UpdateFailed(str(err)) from err
        except OkpAuthError as auth_err:
            # CoolKit token expired/rejected: renew it without touching the
            # password login (which would kick the phone app session). Every
            # failed cycle counts, including the ones that only wait out the
            # cooldown — otherwise the "re-authentication required" prompt
            # would take half an hour to show up.
            #
            # v1.5.1: the cloud said "401 cannot found access token info" for
            # a token it had issued itself. Stopping at a reauth prompt hides
            # *who* took the session, so one more cause is ruled out first:
            # the cloud may accept a session only once its predecessor was
            # released (a QR login does log out the previous client). If the
            # refresh token can mint a new session, nothing was taken - the
            # old access token was simply revoked - so try it before any
            # prompt. Once per process: if the token is refused too, repeating
            # the probe every cycle would only burn the session.
            now = time.time()
            if self.api.coolkit_rt and not self._rt_probe_done:
                self._rt_probe_done = True
                try:
                    await self.api.logout_coolkit_token()
                except (OkpApiError, OkpAuthError) as exc:
                    _LOGGER.debug("OKP explicit logout before renewal failed: %s", exc)
                except Exception as exc:  # noqa: BLE001 - never block recovery
                    # v1.5.2: the release call is best effort. It must never
                    # stop the renewal below, so even an unexpected error
                    # (a NameError in an unreleased build did exactly that and
                    # left the whole first refresh "unknown") is swallowed.
                    _LOGGER.debug("OKP explicit logout raised unexpectedly: %s", exc)
                try:
                    if await self.api.refresh_coolkit_by_rt():
                        item = await self.api.get_thing_state(self.device_id)
                        self._persist_tokens()
                        self.last_rt_probe_at = now
                        self.last_rt_probe_result = "renewed"
                        _LOGGER.info(
                            "OKP session renewed after the cloud rejected the "
                            "access token; the refresh token was still valid"
                        )
                        return item
                except (OkpApiError, OkpAuthError) as exc:
                    self.last_rt_probe_at = now
                    self.last_rt_probe_result = f"rejected: {exc}"
                    _LOGGER.warning(
                        "OKP refresh token rejected after the cloud revoked the "
                        "access token: %s - the session was taken over, not lost "
                        "locally",
                        exc,
                    )
            elif not self.api.coolkit_rt:
                self.last_rt_probe_at = now
                self.last_rt_probe_result = "no refresh token held"
            # v1.4.11: two failure qualities, two different speeds;
            # v1.5.2: the probe above is best effort - it must never abort the
            # accounting below, or the reauth prompt never fires and the entry
            # sits in "unknown" forever.
            #
            # The refresh token is gone (the cloud rejected it in
            # refresh_coolkit_by_rt, which clears it): only a password login
            # can recover, so count at full weight. While an rt is still held
            # this is a transient failure - cloud flakiness, a header
            # rejection, a hiccup - and it advances at half speed: three
            # consecutive hiccups must no longer shove a password form at the
            # user, because that form costs the phone app session.
            step = 2 if not self.api.coolkit_rt else 1
            self._auth_failures = min(
                self._auth_failures + step, REAUTH_AFTER_FAILURES
            )
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
                self.last_error_was_auth = True
                self._log_auth_failure(err)
                if self._auth_failures >= REAUTH_AFTER_FAILURES:
                    await self._maybe_trigger_reauth(err)
                raise UpdateFailed(str(err)) from err
        except OkpApiError as err:
            self.last_error = str(err)
            self.last_error_was_auth = False
            _LOGGER.warning("OKP state fetch failed: %s", err)
            raise UpdateFailed(str(err)) from err
        self.last_error = None
        self.last_error_was_auth = False
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
