"""OKP Cloud vacuum integration."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import OkpApi, OkpApiError, OkpAuthError
from .const import (
    AT_LIFETIME_FALLBACK_SECONDS,
    CONF_PASSWORD,
    CONF_REALTIME,
    CONF_REALTIME_DEFAULT,
    DOMAIN,
    MOVE_DEFAULT_DURATION,
    MOVE_DIRECTIONS,
    MOVE_HOLD_MAX_SECONDS,
    MOVE_RELEASE_VALUE,
    MOVE_STOP,
    PLATFORMS,
    SERVICE_MOVE,
    SERVICE_REFRESH_SESSION,
    SERVICE_RESCAN_DEVICES,
    SERVICE_SET_TIMER,
    ROBOT_DP_HINTS,
    SETUP_RETRY_SECONDS,
    coolkit_app_id,
    persisted_token_fields,
)
from .coordinator import OkpCoordinator
from .ws import OkpRealtime

_LOGGER = logging.getLogger(__name__)

# Devices list storage key inside entry.data (v1.1.9+).
DEVICES_KEY = "devices"


async def _async_refresh_session(call: ServiceCall) -> dict[str, Any]:
    """Report the session state, and only renew it when explicitly asked.

    v1.2.9: the access token is long-lived (weeks), so the ``rt`` renewal path
    would otherwise only be exercised when it is already too late to tell a
    working renewal from a lucky cache hit.

    v1.4.11: *reporting* and *renewing* are no longer the same action. The
    CoolKit cloud rotates the refresh token on renewal and invalidates what it
    issued before, so a "just checking" call used to burn the only session
    that does not depend on the phone app - exactly what happened during the
    v1.4.10 deployment test. The service is therefore dry by default: it
    reports what it knows from stored state and the last poll. Pass
    ``force: true`` to actually renew.
    """
    hass: HomeAssistant = call.hass
    force = bool(call.data.get("force"))
    entries: list[dict[str, Any]] = []
    # Iterate a snapshot: persisting tokens updates the config entry, and an
    # options change can reload it, both of which mutate hass.data[DOMAIN].
    for entry_id, store in list((hass.data.get(DOMAIN) or {}).items()):
        if not isinstance(store, dict) or "api" not in store:
            continue
        api: OkpApi = store["api"]
        coordinators: dict[str, OkpCoordinator] = store.get("coordinators") or {}
        realtime: OkpRealtime | None = store.get("realtime")
        refreshed_by: str | None = None
        error: str | None = None

        if force and realtime is not None and realtime.socket_at:
            # v1.5.3: an open socket owns the account's single session. Forcing
            # a renewal here rotates the token under it and the socket's next
            # ``userOnline`` invalidates whatever the rotation produced - the
            # exact chain that ends in "cannot found access token info".
            # Report instead of renewing; the user can close realtime first if
            # they genuinely need a fresh token right now.
            error = (
                "realtime socket holds the session; renewal skipped "
                "(disable realtime or reload the integration to force one)"
            )
        elif force:
            renewed = False
            try:
                renewed = await api.refresh_coolkit_by_rt()
            except (OkpApiError, OkpAuthError) as err:
                error = str(err)
            if renewed:
                refreshed_by = "rt"
            elif not api.coolkit_rt:
                # No usable refresh token: fall back to the okplife route,
                # which needs a live OKP access token.
                rt_error = error or "no refresh token stored"
                try:
                    await api.refresh_coolkit_token()
                    refreshed_by = "okplife"
                    error = f"rt unavailable ({rt_error})"
                except (OkpApiError, OkpAuthError) as err2:
                    error = f"rt: {rt_error}; okplife: {err2}"
            # else: an rt is still held and the renewal failed transiently -
            # keep the rt route authoritative instead of falling through to
            # the app-dependent okplife route (same rule as
            # ensure_coolkit_token()). The poll cycle retries.
        else:
            error = api.last_rt_error

        if refreshed_by:
            for coordinator in coordinators.values():
                coordinator.async_persist_tokens(force=True)
            # The open socket still holds the previous access token; drop it so
            # the next iteration handshakes with the new one.
            if realtime is not None:
                realtime.async_reconnect()

        last_auth_error = next(
            (
                c.last_error
                for c in coordinators.values()
                if c.last_error_was_auth and c.last_error
            ),
            None,
        )
        entry = hass.config_entries.async_get_entry(entry_id)
        entries.append(
            {
                "entry_id": entry_id,
                "mode": "renew" if force else "report",
                "refreshed_by": refreshed_by,
                "session_state": api.session_state,
                "has_refresh_token": bool(api.coolkit_rt),
                "token_expires_at": api.coolkit_at_expire or None,
                "token_expires_in_seconds": (
                    max(0, api.coolkit_at_expire - int(time.time()))
                    if api.coolkit_at_expire
                    else None
                ),
                "token_expiry_source": (
                    "inferred" if api.at_expire_inferred else "cloud"
                ),
                "token_age_seconds": (
                    int(time.time() - api.coolkit_refreshed_at)
                    if api.coolkit_refreshed_at
                    else None
                ),
                "rt_issued_at": api.coolkit_rt_issued_at or None,
                "rt_rejected_at": api.coolkit_rt_rejected_at or None,
                "rt_reject_count": api.coolkit_rt_reject_count,
                # v1.5.1: who owns the current session and when it started,
                # plus the outcome of the last "did the refresh token
                # survive?" probe. Together with rt_issued_at these answer the
                # only question that matters here: was the session taken by
                # the app, or lost by the integration?
                "session_origin": api.session_origin,
                "session_started_at": api.session_started_at or None,
                # v1.5.3: True while the realtime socket owns the session (and
                # therefore no renewal may run). False means the poll owns it
                # and may renew freely.
                "session_held_by_socket": bool(api.session_socket_at),
                "last_rt_probe_at": (
                    min(
                        (
                            c.last_rt_probe_at
                            for c in coordinators.values()
                            if c.last_rt_probe_at
                        ),
                        default=0.0,
                    )
                    or None
                ),
                "last_rt_probe_result": next(
                    (
                        c.last_rt_probe_result
                        for c in coordinators.values()
                        if c.last_rt_probe_result
                    ),
                    None,
                ),
                "last_auth_error": last_auth_error,
                "reauth_pending": bool(
                    entry is not None and entry.state is ConfigEntryState.SETUP_ERROR
                ),
                "refresh_fields": api.last_refresh_fields,
                # v1.5.4: verdict of every candidate the last renewal tried.
                # An rt that answers 402/403 is genuinely dead; one that only
                # ever sees a 401 on the *access token* candidate was never
                # reached. This list is what tells the two apart.
                "refresh_attempts": api.last_refresh_attempts,
                # v1.5.5: why the session ended, in plain language. Without
                # this the user only saw "stale" and had to guess whether the
                # app had been opened - the one piece of information that
                # decides what to do next. See api.session_end_reason.
                "session_end_reason": api.session_end_reason,
                "at_lifetime_hours": round(api.at_lifetime / 3600, 1),
                "realtime": realtime.state if realtime is not None else None,
                "error": error,
            }
        )
        if refreshed_by:
            _LOGGER.info("OKP session renewed on demand via %s", refreshed_by)
        elif force:
            _LOGGER.warning("OKP on-demand renewal failed: %s", error)
        else:
            _LOGGER.debug("OKP session reported (dry run, nothing renewed)")

    return {"entries": entries}


def _pick_coordinator(hass: HomeAssistant, device_id: str | None) -> OkpCoordinator:
    """Resolve the coordinator a service call targets.

    With a single robot (the common case) no target is needed; with several,
    the caller passes ``device_id`` (the CoolKit id, as used in entity ids).
    """
    found: list[tuple[str, OkpCoordinator]] = []
    for store in (hass.data.get(DOMAIN) or {}).values():
        if not isinstance(store, dict):
            continue
        for key, coordinator in (store.get("coordinators") or {}).items():
            found.append((key, coordinator))
    if device_id:
        for key, coordinator in found:
            if key == device_id:
                return coordinator
        raise ValueError(f"no OKP device with id {device_id}")
    if len(found) == 1:
        return found[0][1]
    if not found:
        raise ValueError("the OKP Cloud integration is not set up")
    known = ", ".join(key for key, _ in found)
    raise ValueError(f"several OKP devices, pass device_id (one of: {known})")


async def _async_set_timer(call: ServiceCall) -> dict[str, Any]:
    """Enable or disable one device-side schedule.

    v1.3.0: the app's scheduled-clean screen toggles a schedule by rewriting
    the whole ``timers`` dp; there is no per-schedule cloud endpoint. This
    service does the same read-modify-write but re-reads the list right before
    writing and verifies the result, so an out-of-date snapshot cannot
    resurrect schedules that were deleted in the app.
    """
    hass: HomeAssistant = call.hass
    data = call.data
    mid = str(data.get("mid") or "").strip()
    if not mid:
        raise ValueError("mid is required (see the timers sensor attributes)")
    enabled = bool(data.get("enabled"))
    coordinator = _pick_coordinator(hass, data.get("device_id"))

    try:
        changed = await coordinator.async_set_timer_enabled(mid, enabled)
    except (OkpApiError, OkpAuthError) as err:
        raise HomeAssistantError(f"OKP 定时任务操作失败：{err}") from err
    timers = coordinator.timers()
    return {
        "mid": mid,
        "enabled": enabled,
        "changed": changed,
        "timers": timers,
    }


async def _async_move(call: ServiceCall) -> dict[str, Any]:
    """Drive the robot by hand, the way the app's joystick does.

    Two things this has to get right, because a robot is not a lamp:

    * **release** - the app writes ``{"move": 4}`` when the finger lifts. If the
      caller passes a duration we do that for them (and also when the call is
      cancelled); with ``duration: 0`` the direction stays held and the
      coordinator's watchdog releases it after 10 s at the latest.
    * **one at a time** - overlapping calls are serialised by the coordinator,
      so a second press cannot silently cancel the first one's release.
    """
    data = call.data
    raw = data.get("value")
    direction = (data.get("direction") or "").strip().lower()
    duration = data.get("duration")
    duration = MOVE_DEFAULT_DURATION if duration is None else float(duration)

    if raw is not None and direction:
        raise ValueError("pass either direction or value, not both")
    if raw is None and not direction:
        raise ValueError("direction is required (or a raw value 0-4)")
    if duration < 0 or duration > MOVE_HOLD_MAX_SECONDS:
        raise ValueError(f"duration must be between 0 and {MOVE_HOLD_MAX_SECONDS:g} s")

    if raw is not None:
        value = int(raw)
        if value < 0 or value > MOVE_RELEASE_VALUE:
            raise ValueError("value must be 0-3 (direction) or 4 (release)")
    elif direction == MOVE_STOP:
        value = MOVE_RELEASE_VALUE
    else:
        value = MOVE_DIRECTIONS.get(direction)
        if value is None:
            known = ", ".join(sorted(MOVE_DIRECTIONS)) + ", " + MOVE_STOP
            raise ValueError(f"unknown direction '{direction}' (known: {known})")

    coordinator = _pick_coordinator(call.hass, data.get("device_id"))
    try:
        result = await coordinator.async_move(value, duration)
    except (OkpApiError, OkpAuthError) as err:
        raise HomeAssistantError(f"OKP 手动遥控失败：{err}") from err
    coordinator.async_schedule_refresh((3.0,))
    return {"direction": direction or None, "value": value, **result}


def _is_robot_params(params: Any) -> bool:
    """Heuristic: does this CoolKit thing look like one of our robots?

    The CoolKit thing list contains *every* device type the account (or the
    brands its appid is licensed for) has. Robots are recognised by the dp
    keys the v3.4.0 app capture showed on the K5 Ultra - shared across the
    OKP range, since those dps are what the app's robot pages bind to. A
    device matching none of them is left alone: guessing would create a
    vacuum entity for something that cannot sweep.
    """
    if not isinstance(params, dict):
        return False
    keys = set(params)
    return any(hint in keys for hint in ROBOT_DP_HINTS)


async def _async_rescan_devices(call: ServiceCall) -> dict[str, Any]:
    """Re-read the account's device list and pick up new robots (v1.6.0).

    Two sources, in order of preference:

    1. CoolKit ``GET /v2/device/thing`` - needs only the long-lived CoolKit
       access token, so this works months after the last password entry and
       is the path that makes "buy a new robot, run the service, done" real.
       It also sees devices shared *to* this account (itemType 2), which is
       what the v1.5.5 shared-account setup relies on.
    2. OKP home/device list - only when the CoolKit route cannot answer.
       Needs the OKP login token, which may be long expired.

    Newly found robots are merged into the entry's device list and the entry
    reloads itself, so entities appear without any password prompt. Devices
    that vanished from the cloud are kept: removing hardware should be a
    deliberate act, not a side effect of a network hiccup.
    """
    hass: HomeAssistant = call.hass
    results: list[dict[str, Any]] = []
    for entry_id, store in list((hass.data.get(DOMAIN) or {}).items()):
        if not isinstance(store, dict) or "api" not in store:
            continue
        api: OkpApi = store["api"]
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            continue

        found: dict[str, dict[str, Any]] = {}
        source = None
        try:
            things = await api.list_coolkit_things()
            source = "coolkit"
            for dev in things:
                if _is_robot_params(dev.get("params")):
                    found[dev["third_dev_id"]] = dev
        except (OkpApiError, OkpAuthError) as err:
            _LOGGER.debug("OKP rescan via CoolKit failed (%s); trying OKP", err)
            try:
                homes = await api.get_homes()
                for home in homes:
                    home_id = str(home.get("home_id") or home.get("id"))
                    for dev in await api.get_devices(home_id):
                        third = dev.get("third_dev_id")
                        if third:
                            found[str(third)] = {
                                "id": str(dev.get("id")),
                                "name": dev.get("name"),
                                "third_dev_id": str(third),
                                "product_id": dev.get("third_product_id_tuya"),
                                "model": dev.get("device_model_name"),
                            }
                source = "okplife"
            except (OkpApiError, OkpAuthError) as err2:
                raise HomeAssistantError(
                    f"OKP 重新扫描失败：CoolKit ({err}) 与 OKP 云 ({err2}) 均不可用"
                ) from err2

        existing = {
            str(d.get("third_dev_id")): d
            for d in _device_list(entry)
            if d.get("third_dev_id")
        }
        added = sorted(set(found) - set(existing))
        # Deliberate no-delete policy (see docstring): only additions merge.
        merged = list(existing.values())
        for dev_id in added:
            dev = found[dev_id]
            merged.append(
                {
                    "id": dev["id"],
                    "name": dev.get("name"),
                    "third_dev_id": dev["third_dev_id"],
                    "product_id": dev.get("product_id"),
                    "model": dev.get("model"),
                }
            )
        merged.sort(key=lambda d: str(d.get("name") or d.get("third_dev_id")))

        if added:
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, DEVICES_KEY: merged}
            )
            await hass.config_entries.async_reload(entry_id)

        results.append(
            {
                "entry_id": entry_id,
                "source": source,
                "known": len(existing),
                "discovered": len(found),
                "added": [
                    {"name": found[i].get("name"), "device_id": i} for i in added
                ],
                "reloaded": bool(added),
            }
        )
    return {"entries": results}


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the integration services once."""
    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH_SESSION):
        hass.services.async_register(
            DOMAIN,
            SERVICE_REFRESH_SESSION,
            _async_refresh_session,
            supports_response=SupportsResponse.ONLY,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_SET_TIMER):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_TIMER,
            _async_set_timer,
            supports_response=SupportsResponse.OPTIONAL,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_MOVE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_MOVE,
            _async_move,
            supports_response=SupportsResponse.OPTIONAL,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_RESCAN_DEVICES):
        hass.services.async_register(
            DOMAIN,
            SERVICE_RESCAN_DEVICES,
            _async_rescan_devices,
            supports_response=SupportsResponse.ONLY,
        )


def _device_list(entry: ConfigEntry) -> list[dict]:
    """Resolve the device list from entry.data (legacy entries migrate on setup)."""
    devices = entry.data.get(DEVICES_KEY)
    if isinstance(devices, list) and devices:
        return devices
    # Legacy (< v1.1.9) entry: single flat device fields.
    third_dev_id = entry.data.get("third_dev_id")
    if third_dev_id:
        return [
            {
                "id": entry.data.get("device_id"),
                "name": entry.data.get("device_name"),
                "third_dev_id": third_dev_id,
                "product_id": entry.data.get("product_id"),
                "model": entry.data.get("model"),
            }
        ]
    return []


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OKP Cloud from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    # Migration (v1.1.8): entries created before this version may still hold
    # a plain-text password in data; drop it now that the integration runs
    # purely on the CoolKit token (login only happens transiently in flows).
    # NB: ConfigEntry.data is read-only on newer HA — always go through
    # async_update_entry, never assign entry.data directly (raises
    # "data cannot be changed directly" and aborts setup).
    new_data = {k: v for k, v in entry.data.items() if k != CONF_PASSWORD}
    # Migration (v1.1.9): backfill the devices list for legacy entries.
    devices = _device_list(entry)
    if not devices:
        raise ValueError("no devices in config entry data")
    if DEVICES_KEY not in entry.data:
        new_data[DEVICES_KEY] = devices
    if new_data != entry.data:
        hass.config_entries.async_update_entry(entry, data=new_data)

    _async_register_services(hass)

    session = async_create_clientsession(hass)
    api = OkpApi(session)
    api.access_token = entry.data.get("access_token")
    api.user_id = entry.data.get("user_id")
    # Reuse a stored CoolKit token pair when available (avoids an extra
    # refresh request on startup). The refresh token is what keeps the
    # session alive once the OKP access token expires, so it is restored
    # alongside the access token.
    api.coolkit_at = entry.data.get("coolkit_at")
    api.coolkit_rt = entry.data.get("coolkit_rt")
    api.coolkit_apikey = entry.data.get("coolkit_apikey")
    api.coolkit_region = entry.data.get("coolkit_region")
    # v1.5.5: speak as the appid this entry was configured with. Entries that
    # predate the option have no key and fall back to the OKP app id, i.e. the
    # previous behaviour. It must be set before any request is made: mixing
    # appids inside one session is answered with 401 and looks like a dead
    # session instead of a configuration mistake.
    api.coolkit_appid = coolkit_app_id(entry.data)
    if api.coolkit_at:
        api.coolkit_at_expire = int(entry.data.get("coolkit_at_expire") or 0)
        # v1.2.12: keep the diagnostic honest across restarts - an expiry that
        # was inferred locally must not be reported as cloud-provided.
        api.at_expire_inferred = bool(entry.data.get("coolkit_at_expire_inferred"))
    api.at_lifetime = int(
        entry.data.get("coolkit_at_lifetime") or 0
    ) or AT_LIFETIME_FALLBACK_SECONDS
    # v1.4.11: rt issue/rejection bookkeeping survives a restart, so a
    # post-mortem ("who took the session, and when") still has the timestamps.
    api.coolkit_rt_issued_at = float(entry.data.get("coolkit_rt_issued_at") or 0)
    api.coolkit_rt_rejected_at = float(entry.data.get("coolkit_rt_rejected_at") or 0)
    api.coolkit_rt_reject_count = int(entry.data.get("coolkit_rt_reject_count") or 0)
    # v1.5.1: provenance of the restored session (which path obtained it).
    api.session_origin = entry.data.get("coolkit_session_origin") or (
        "unknown" if (api.coolkit_at or api.coolkit_rt) else "none"
    )
    api.session_started_at = float(entry.data.get("coolkit_session_started_at") or 0)

    # v1.5.0: startup self-check. A "half a token pair" entry (an at with no
    # expiry, or an at with no refresh timestamp) is what older builds wrote
    # when the reauth flow hand-picked keys. Those entries load, serve one
    # session, then fail with "401 cannot found access token info" on the next
    # restart - so rather than entering the poll with a session of unknown
    # quality, say it out loud and renew before the first read.
    restored = {
        "has_at": bool(api.coolkit_at),
        "has_rt": bool(api.coolkit_rt),
        "at_expire": api.coolkit_at_expire,
        "at_expire_inferred": api.at_expire_inferred,
        "rt_issued_at": int(api.coolkit_rt_issued_at) or None,
        "session_origin": api.session_origin,
        "session_started_at": int(api.session_started_at) or None,
    }
    _LOGGER.debug("OKP session restored from the config entry: %s", restored)
    if api.coolkit_rt and (not api.coolkit_at or not api.coolkit_at_expire):
        _LOGGER.warning(
            "OKP config entry held an incomplete token pair (%s); renewing "
            "with the refresh token before the first poll",
            restored,
        )
        try:
            await api.refresh_coolkit_by_rt()
        except (OkpApiError, OkpAuthError) as err:
            # Non-fatal: the poll cycle retries and prompts for reauth if the
            # refresh token is gone for good.
            _LOGGER.debug("OKP startup renewal from rt failed: %s", err)
        else:
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, **persisted_token_fields(api)}
            )
            _LOGGER.info(
                "OKP startup renewal succeeded (at expires %s, source %s)",
                api.coolkit_at_expire or "unknown",
                "inferred" if api.at_expire_inferred else "cloud",
            )

    # Upgrade path for entries created before v1.2.2 (only `coolkit_at` was
    # stored): mint a refresh token while the OKP access token still works,
    # otherwise the session dies as soon as the CoolKit token expires.
    if not api.coolkit_rt and api.access_token:
        try:
            await api.refresh_coolkit_token()
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, **persisted_token_fields(api)}
            )
            _LOGGER.debug("OKP CoolKit refresh token captured on setup")
        except (OkpApiError, OkpAuthError) as err:
            # Non-fatal: the poll cycle retries and raises reauth if needed.
            _LOGGER.debug("OKP could not capture a CoolKit refresh token: %s", err)

    # v1.5.1: an entry written before this version carries no provenance.
    # Persist what we restored so the next restart (and any post-mortem) can
    # still tell which path produced the session. Only fills blanks - a
    # restored origin is never overwritten here.
    if api.session_origin == "unknown":
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, **persisted_token_fields(api)}
        )

    # One coordinator per robot: independent poll cycle, map cache and
    # per-device entity state.
    coordinators: dict[str, OkpCoordinator] = {}
    for dev in devices:
        third = dev.get("third_dev_id")
        if not third:
            continue
        coordinators[third] = OkpCoordinator(hass, api, third, entry.entry_id)

    # First refresh for every coordinator (parallel) before platforms load.
    #
    # A failed first refresh normally raises ConfigEntryNotReady and parks the
    # whole entry in HA's "retrying setup" loop. That is the wrong signal here:
    # the realistic causes are an expired cloud session (needs a reauth prompt)
    # or a cloud hiccup (needs another try), not a broken configuration. Load
    # the platforms anyway so the entities keep their last values, and keep the
    # poll loop alive from here - HA does *not* schedule the interval refresh
    # when async_config_entry_first_refresh() raises, which used to leave the
    # coordinator polling never (frozen last_poll_at, auth_failures stuck at 1,
    # no reauth prompt, entry dead until a manual reload).
    reauth_errors: list[tuple[OkpCoordinator, BaseException]] = []
    if coordinators:
        results = await asyncio.gather(
            *(c.async_config_entry_first_refresh() for c in coordinators.values()),
            return_exceptions=True,
        )
        for coordinator, result in zip(coordinators.values(), results):
            if not isinstance(result, BaseException):
                continue
            _LOGGER.warning(
                "OKP first refresh failed (retrying every %ss): %s",
                SETUP_RETRY_SECONDS,
                result,
            )
            if coordinator.last_error_was_auth:
                # Credentials, not the network: a password login is the only
                # way out, so ask for it now instead of after three cycles that
                # may never arrive.
                reauth_errors.append((coordinator, result))
            task = hass.async_create_background_task(
                coordinator.async_setup_retry_loop(),
                f"okp_cloud setup retry {coordinator.device_id}",
            )
            # NB: never register ``task.cancel`` directly - it returns True and
            # Home Assistant treats a non-None return of an unload callback as
            # an awaitable, which fails the whole unload with "a coroutine was
            # expected, got True" (entry stuck in failed_unload, reload dead).
            def _cancel_retry_task(task: asyncio.Task = task) -> None:
                task.cancel()

            entry.async_on_unload(_cancel_retry_task)

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinators": coordinators,
    }

    # v1.3.3: open the realtime socket the v3.4.0 app uses, so a robot that is
    # cleaning shows up in Home Assistant within a second instead of within
    # three minutes. It is a pure accelerator: the poll below keeps running and
    # everything still works when the socket cannot be established.
    realtime: OkpRealtime | None = None
    wanted = entry.options.get(CONF_REALTIME, CONF_REALTIME_DEFAULT)
    if wanted:
        # v1.5.5: a second account reached through device sharing only sees
        # the devices in *its own* thing list, which is exactly the case when
        # the user has no CoolKit apikey of their own to hand us: fetch it
        # from the cloud instead of refusing to start the socket.
        if not api.coolkit_apikey:
            try:
                await api.refresh_coolkit_token()
            except (OkpApiError, OkpAuthError) as err:
                _LOGGER.debug("OKP could not obtain a CoolKit apikey: %s", err)

        def _notify_realtime_state() -> None:
            """Push the new channel state to the diagnostic sensor."""
            for coordinator in coordinators.values():
                coordinator.async_update_listeners()

        realtime = OkpRealtime(
            hass, api, coordinators, state_listener=_notify_realtime_state
        )
        for coordinator in coordinators.values():
            coordinator.realtime = realtime
        hass.data[DOMAIN][entry.entry_id]["realtime"] = realtime
        realtime.async_start()

    # Options (currently only the realtime toggle) are applied by reloading:
    # starting/stopping the socket in place would need the platforms to pick up
    # a new coordinator, and a reload is cheap for a cloud integration.
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Raised last, once the platforms exist: a reauth flow started mid-setup
    # can race with the entity registration above.
    for coordinator, err in reauth_errors:
        await coordinator.async_trigger_reauth(err)

    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when the realtime option changed.

    Deliberately *not* a blanket "reload on update": the coordinator writes
    renewed tokens into ``entry.data`` several times a day, and every one of
    those writes fires this listener. Reloading on them would tear down the
    integration - and, worse, would replace ``hass.data[DOMAIN]`` while a
    service iterates it ("dictionary changed size during iteration"). Only a
    change between "option says on" and "a socket actually exists" is acted on.
    """
    store = (hass.data.get(DOMAIN) or {}).get(entry.entry_id) or {}
    wanted = bool(entry.options.get(CONF_REALTIME, CONF_REALTIME_DEFAULT))
    running = store.get("realtime") is not None
    if wanted == running:
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        store = hass.data[DOMAIN].pop(entry.entry_id, None) or {}
        for coordinator in (store.get("coordinators") or {}).values():
            # A remote-control press must not survive an unload/reload.
            await coordinator.async_shutdown_move()
        realtime = store.get("realtime")
        if realtime is not None:
            # Close the socket before dropping the entry, otherwise the task
            # keeps receiving pushes for coordinators that no longer exist.
            await realtime.async_stop()
        # Session is created via async_create_clientsession(hass) and is
        # managed by Home Assistant; integrations must NOT close it
        # (deprecated since HA 2026.x, will fail in 2027.9).
    return unload_ok
