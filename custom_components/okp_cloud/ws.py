"""CoolKit websocket push channel.

The v3.4.0 app does not poll: it keeps a websocket open to a regional CoolKit
node and receives every device change the moment the robot reports it. This
module does the same for the integration.

Two rules keep it safe:

* **Read-only.** Nothing is ever written over this socket. Control calls keep
  using the documented HTTP endpoint, so a socket that misbehaves can never
  put the robot into a state the app would not produce.
* **Pure accelerator.** The 180 s HTTP poll keeps running untouched. If the
  socket cannot be established (no ``apikey``, an expired token, too many
  sessions on the account, a blocking router) the integration behaves exactly
  like it did before - slower, but complete. The socket only ever *adds*
  freshness.

The protocol was reconstructed from the v3.4.0 app capture:

    GET https://cn-dispa.coolkit.cn/dispatch/app   -> {"domain","port","IP"}
    wss://<domain>:<port>/api/ws
    -> {"action":"userOnline","apikey","appid","at","nonce","","sequence"<ms>,
        "ts"<s>,"userAgent":"app","version":8}
    <- {"error":0,"config":{"hb":1,"hbInterval":145},"sequence"}
    -> "ping"  /  <- "pong"                       (about every hbInterval/2)
    <- {"action":"update","deviceid","apikey","userAgent":"device","d_seq",
        "params":{...}}                           (full or partial dp set)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any

import aiohttp

from .const import (
    CK_APP_ID,
    CK_DOMAIN,
    DOMAIN,
    WS_DISPATCH_URL,
    WS_DISPATCH_URL_TEMPLATE,
    WS_HANDSHAKE_TIMEOUT,
    WS_HB_INTERVAL_FALLBACK,
    WS_PATH,
    WS_RECONNECT_DELAYS,
    WS_USER_VERSION,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .api import OkpApi
    from .coordinator import OkpCoordinator

_LOGGER = logging.getLogger(__name__)

# Socket states surfaced by the "realtime" diagnostic sensor.
STATE_IDLE = "idle"
STATE_DISABLED = "disabled"
STATE_CONNECTING = "connecting"
STATE_CONNECTED = "connected"
STATE_DISCONNECTED = "disconnected"
STATE_ERROR = "error"


class OkpRealtime:
    """Keep a CoolKit socket open and forward device pushes to the coordinators."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: OkpApi,
        coordinators: dict[str, OkpCoordinator],
    ) -> None:
        self.hass = hass
        self.api = api
        self._coordinators = coordinators
        self._task: asyncio.Task | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._closing = False
        # Set when *we* closed the socket on purpose (token renewal), so the
        # read loop can exit quietly instead of reporting a cloud-side drop.
        self._closed_by_us = False
        self._reconnect_requested = False
        # Diagnostic state (read by the realtime sensor).
        self.state = STATE_IDLE
        self.host: str | None = None
        self.last_error: str | None = None
        self.connected_since: float | None = None
        self.last_message_at: float | None = None
        self.messages = 0
        self.pushes = 0
        self.reconnects = 0
        self._attempt = 0
        # Last failure already logged, so a permanently unreachable socket
        # writes one line instead of one per retry.
        self._logged_error: str | None = None

    # -- lifecycle --------------------------------------------------------

    def async_start(self) -> None:
        """Start the background socket task (idempotent)."""
        if self._task is not None and not self._task.done():
            return
        self._closing = False
        self._task = self.hass.async_create_background_task(
            self._async_run(), f"{DOMAIN}_realtime", eager_start=False
        )

    async def async_stop(self) -> None:
        """Close the socket and stop the task (config entry unload)."""
        self._closing = True
        await self._async_close_ws()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001 - shutdown must not raise
                pass
            self._task = None
        self.state = STATE_IDLE

    def async_reconnect(self) -> None:
        """Drop the current socket so the next loop iteration re-handshakes.

        Called after a token renewal: the running socket holds the *old*
        access token, and the cloud may invalidate it at any time.
        """
        self._attempt = 0
        self._logged_error = None
        self._reconnect_requested = True
        self._closed_by_us = True
        if self._ws is not None and not self._ws.closed:
            self.hass.async_create_task(self._async_close_ws())

    async def _async_close_ws(self) -> None:
        ws = self._ws
        if ws is not None and not ws.closed:
            self._closed_by_us = True
            try:
                await ws.close()
            except Exception:  # noqa: BLE001 - closing is best effort
                pass
        # Only forget the socket we actually closed: a reconnect may already
        # have installed a new one while this task was waiting.
        if self._ws is ws:
            self._ws = None

    # -- main loop --------------------------------------------------------

    async def _async_run(self) -> None:
        while not self._closing:
            started = time.time()
            try:
                await self._async_session()
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - never let the task die
                self.last_error = str(err) or type(err).__name__
                if self.state != STATE_DISABLED:
                    self.state = STATE_ERROR
                self._log_once(self.last_error)

            if self._closing:
                break
            # A connection that lasted a while resets the backoff; a socket
            # that dies right after the handshake backs off quickly instead of
            # reconnect-looping against the cloud.
            if time.time() - started > 120:
                self._attempt = 0
            delay = WS_RECONNECT_DELAYS[
                min(self._attempt, len(WS_RECONNECT_DELAYS) - 1)
            ]
            self._attempt += 1
            self.reconnects += 1
            if delay:
                await asyncio.sleep(delay)

    def _log_once(self, message: str) -> None:
        if message == self._logged_error:
            _LOGGER.debug("OKP realtime still unavailable: %s", message)
            return
        self._logged_error = message
        _LOGGER.warning(
            "OKP realtime unavailable (%s); the 180 s poll keeps the entities "
            "updated",
            message,
        )

    async def _async_session(self) -> None:
        """One connect / handshake / read cycle."""
        self._closed_by_us = False
        self._reconnect_requested = False
        if not self.api.coolkit_at or not self.api.coolkit_apikey:
            # Nothing to authenticate with yet. Not an error worth warning
            # about: the poll cycle is still working on it.
            self.state = STATE_DISABLED
            raise RuntimeError("no CoolKit token/apikey to open a socket with")

        self.state = STATE_CONNECTING
        # Renew first when the token is about to die, otherwise the handshake
        # is rejected and the socket looks broken for no good reason.
        await self.api.ensure_coolkit_token()
        dispatch = await self._async_dispatch()
        host = dispatch.get("domain") or dispatch.get("IP")
        if not host:
            raise RuntimeError("dispatch returned no host")
        port = int(dispatch.get("port") or 443)
        self.host = f"{host}:{port}"
        url = f"wss://{host}:{port}{WS_PATH}"

        async with self.api.session.ws_connect(
            url,
            heartbeat=None,  # the app uses its own text ping/pong
            timeout=aiohttp.ClientTimeout(total=WS_HANDSHAKE_TIMEOUT),
            max_msg_size=0,
        ) as ws:
            self._ws = ws
            try:
                hb_interval = await self._async_handshake(ws)
                ping_task = self.hass.async_create_background_task(
                    self._async_ping(ws, hb_interval),
                    f"{DOMAIN}_realtime_ping",
                    eager_start=False,
                )
                try:
                    await self._async_read(ws, hb_interval)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    # Closing a socket from another task does not always make
                    # the pending receive() return a CLOSE frame - depending on
                    # timing it surfaces as ConnectionResetError instead. Either
                    # way it is *our* close, so it must not be reported as a
                    # cloud-side drop.
                    if not (self._reconnect_requested or self._closing):
                        raise
                finally:
                    ping_task.cancel()
            finally:
                self._ws = None
                if self.state == STATE_CONNECTED:
                    self.state = STATE_DISCONNECTED

    # -- protocol steps ---------------------------------------------------

    def _dispatch_url(self) -> str:
        region = (self.api.coolkit_region or "cn").lower()
        if region in ("", "cn"):
            return WS_DISPATCH_URL
        return WS_DISPATCH_URL_TEMPLATE.format(region=region, suffix="cc")

    async def _async_dispatch(self) -> dict[str, Any]:
        """Ask the cloud which node this account belongs to."""
        headers = {
            "authorization": f"Bearer {self.api.coolkit_at}",
            "x-ck-appid": CK_APP_ID,
            "domain-name": CK_DOMAIN,
            "content-type": "application/json; charset=utf-8",
            "user-agent": "okhttp/4.10.0",
        }
        try:
            async with self.api.session.get(
                self._dispatch_url(),
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=WS_HANDSHAKE_TIMEOUT),
            ) as resp:
                body = await resp.json(content_type=None)
        except (aiohttp.ClientError, ValueError) as err:
            raise RuntimeError(f"dispatch failed: {err}") from err
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        if not isinstance(data, dict):
            raise RuntimeError("dispatch returned an unexpected body")
        if data.get("error"):
            raise RuntimeError(
                f"dispatch error {data.get('error')}: {data.get('reason') or ''}".strip()
            )
        return data

    async def _async_handshake(self, ws: aiohttp.ClientWebSocketResponse) -> int:
        """Send userOnline and return the heartbeat interval in seconds."""
        now_ms = int(time.time() * 1000)
        await ws.send_json(
            {
                "action": "userOnline",
                "apikey": self.api.coolkit_apikey,
                "appid": CK_APP_ID,
                "at": self.api.coolkit_at,
                "nonce": "",
                "sequence": str(now_ms),
                "ts": int(time.time()),
                "userAgent": "app",
                "version": WS_USER_VERSION,
            }
        )
        msg = await ws.receive(timeout=WS_HANDSHAKE_TIMEOUT)
        if msg.type is not aiohttp.WSMsgType.TEXT:
            raise RuntimeError(
                f"socket closed during handshake ({msg.type.name})"
                + (f": {ws.exception()}" if ws.exception() else "")
            )
        try:
            reply = json.loads(msg.data)
        except ValueError as err:
            raise RuntimeError(f"unexpected handshake reply: {msg.data[:120]!r}") from err
        error = reply.get("error")
        if error:
            reason = reply.get("reason") or reply.get("msg") or ""
            raise RuntimeError(f"handshake rejected: {error} {reason}".strip())
        self.state = STATE_CONNECTED
        self.connected_since = time.time()
        self.last_message_at = self.connected_since
        self.last_error = None
        self._logged_error = None
        config = reply.get("config") or {}
        try:
            hb = int(config.get("hbInterval") or WS_HB_INTERVAL_FALLBACK)
        except (TypeError, ValueError):
            hb = WS_HB_INTERVAL_FALLBACK
        _LOGGER.debug("OKP realtime connected to %s (hb %ss)", self.host, hb)
        return max(30, hb)

    async def _async_ping(
        self, ws: aiohttp.ClientWebSocketResponse, hb_interval: int
    ) -> None:
        """Send the app-level text ping the cloud expects."""
        interval = max(10, hb_interval // 2)
        while not self._closing and not ws.closed:
            await asyncio.sleep(interval)
            if ws.closed:
                return
            try:
                await ws.send_str("ping")
            except (aiohttp.ClientError, RuntimeError):
                return

    async def _async_read(
        self, ws: aiohttp.ClientWebSocketResponse, hb_interval: int
    ) -> None:
        """Read frames until the socket dies."""
        while not self._closing:
            try:
                msg = await ws.receive(timeout=hb_interval)
            except asyncio.TimeoutError as err:
                # No pong within a full heartbeat interval: the TCP connection
                # may look alive while the cloud has already dropped it.
                raise RuntimeError(f"no traffic for {hb_interval}s") from err
            if msg.type is aiohttp.WSMsgType.TEXT:
                self._handle_text(msg.data)
            elif msg.type is aiohttp.WSMsgType.BINARY:
                continue
            elif msg.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.CLOSED,
            ):
                if self._closed_by_us or self._closing:
                    return
                raise RuntimeError("socket closed by the cloud")
            elif msg.type is aiohttp.WSMsgType.ERROR:
                raise RuntimeError(f"socket error: {ws.exception()}")

    # -- frame handling ---------------------------------------------------

    def _handle_text(self, text: str) -> None:
        self.last_message_at = time.time()
        if text == "pong":
            return
        try:
            payload = json.loads(text)
        except ValueError:
            return
        if not isinstance(payload, dict):
            return
        self.messages += 1

        action = payload.get("action")
        if action is None:
            error = payload.get("error")
            if error:
                self.last_error = (
                    f"cloud error {error}: "
                    f"{payload.get('reason') or payload.get('msg') or ''}"
                ).strip()
            return
        if action != "update":
            return

        device_id = payload.get("deviceid")
        params = payload.get("params")
        if not device_id or not isinstance(params, dict) or not params:
            return
        # "app" here means an echo of a write some client just sent (including
        # this integration's own HTTP writes). Only the device's own
        # notification is authoritative.
        if payload.get("userAgent") != "device":
            return
        coordinator = self._coordinators.get(str(device_id))
        if coordinator is None:
            return
        self.pushes += 1
        coordinator.async_apply_push(params)

    # -- diagnostics ------------------------------------------------------

    def diagnostics(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "host": self.host,
            "connected_since": self.connected_since,
            "last_message_at": self.last_message_at,
            "messages_received": self.messages,
            "device_pushes": self.pushes,
            "reconnects": self.reconnects,
            "last_error": self.last_error,
        }
