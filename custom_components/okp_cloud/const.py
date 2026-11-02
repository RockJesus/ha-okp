"""Constants for the OKP Cloud vacuum integration."""

from homeassistant.const import Platform

DOMAIN = "okp_cloud"
PLATFORMS = [
    Platform.VACUUM,
    Platform.SENSOR,
    Platform.CAMERA,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.BUTTON,
]

CONF_ACCOUNT = "account"
CONF_PASSWORD = "password"
# v1.3.3: options key for the realtime push channel.
# v1.4.6: default off. The vendor cloud allows only one "app" session per
# user: opening the OKP phone app tears the socket down and every later
# handshake fails with "406 Authentication Failed" until the app is gone,
# and the app login also invalidates the OKP token chain (4001). Defaulting
# to polling keeps every install safe; the toggle remains opt-in.
CONF_REALTIME = "realtime"
CONF_REALTIME_DEFAULT = False

# okplife REST API
API_BASE = "https://api-cn.okplife.com"
API_BASE_ALT = "https://api.okplife.com"
ENDPOINT_LOGIN = "/v5/client/login-with-password"
ENDPOINT_HOME_LIST = "/v2/home/list"
ENDPOINT_DEVICE_LIST = "/v9/home/device-list"
ENDPOINT_DEVICE_DETAIL = "/v5/home/device-detail-info"
# v1.2.0: the v3.4.0 app exchanges the OKP access token for CoolKit
# credentials via GET /v1/coolkit/get-user-info (refresh-access-token is no
# longer called by the app and may be retired server-side).
ENDPOINT_CK_USER_INFO = "/v1/coolkit/get-user-info"

# CoolKit (thing cloud) API
CK_BASE = "https://cn-apia.coolkit.cn"
CK_ENDPOINT_THING = "/v2/device/thing"
# v1.2.1: write path is /v2/device/thing/status (CoolKit v2 "set device
# status"), body {"type":1,"id":<deviceid>,"params":{...}}. The previous
# "/v2/device/thing/update" does not exist on the gateway and answers
# {"error":403,"msg":"api not found"}, which killed every control call.
CK_ENDPOINT_THING_UPDATE = "/v2/device/thing/status"
CK_ENDPOINT_SWEEP_HISTORY = "/v2/device/sweep-robot-cleanning-history"
CK_ENDPOINT_SWEEP_MAP = "/v2/device/sweep-robot-cleanning-map"
CK_ENDPOINT_OTA_QUERY = "/v2/device/ota/query"
# v1.2.2: CoolKit's own session renewal. Body {"rt": <coolkit_rt>}; returns a
# fresh at/rt pair. This is the only renewal path that does not depend on the
# OKP access token, which expires after a few hours and has no refresh
# endpoint on the okplife side.
CK_ENDPOINT_USER_REFRESH = "/v2/user/refresh"
CK_APP_ID = "fv3LFoaAO65cb5bfaKw6okoHzBVpVX1z"  # x-ck-appid (OKP app)
CK_DOMAIN = "douban"  # domain-name header seen in the OKP app capture

# v1.2.9: on-demand session renewal service. Lets the user (and the release
# verification) force the CoolKit ``rt`` path without waiting for the access
# token to expire, which is the only way to prove the session is independent
# of the phone app.
SERVICE_REFRESH_SESSION = "refresh_session"
# v1.3.0: enable/disable one device-side schedule (the ``timers`` dp) without
# touching the others. The app does the same thing: it rewrites the whole
# ``timers`` array with a single entry's ``enabled`` flag flipped.
SERVICE_SET_TIMER = "set_timer"

# v1.4.2: manual remote (the app's joystick). The capture shows the app
# writing the ``move`` dp while a direction button is *held* and writing 4 when
# it is released -- press/release, not a single "drive N centimetres" command.
# Values 0..3 are the four directions; the mapping below follows the vendor's
# ordering (0 forward, 1 back, 2 left, 3 right) and is *not* verified on the
# unit yet, so the service also accepts a raw ``value`` for a one-off test.
SERVICE_MOVE = "move"
MOVE_DP = "move"
MOVE_RELEASE_VALUE = 4
MOVE_DIRECTIONS = {
    "forward": 0,
    "backward": 1,
    "left": 2,
    "right": 3,
}
MOVE_STOP = "stop"
MOVE_DEFAULT_DURATION = 0.4
# A held direction is released by the caller. If that never happens (card
# closed, script killed, HA restarting) the watchdog releases it, otherwise the
# robot would keep driving until it hits something.
MOVE_HOLD_MAX_SECONDS = 10.0
MOVE_WATCHDOG_GRACE = 2.0

# v1.3.0: dps that the v3.4.0 app capture showed as user-facing settings
# rather than raw diagnostics. Their names come from the vendor's own
# device-detail-info "pid_func_configs" table for this model:
#   dp31          -> func "carpet_detection_switch"  (地毯检测)
#   carpetBooster -> func "carpet_booster_switch"    (地毯增压)
#   call          -> func-less dp: writing 1 makes the robot beep ("查找机器人")
CARPET_DETECTION_DP = "dp31"
CALL_DP = "call"
CARPET_DETECTION_REQUIRES_DP = "dp31"

# v1.3.3: realtime push channel (the v3.4.0 app keeps a websocket open
# instead of polling). Read from the app capture: dispatch/app hands out the
# regional node, the socket lives at /api/ws, and the handshake is a
# "userOnline" frame answered with {"error":0,"config":{"hbInterval":145}}.
WS_DISPATCH_URL = "https://cn-dispa.coolkit.cn/dispatch/app"
WS_DISPATCH_URL_TEMPLATE = "https://{region}-dispa.coolkit.{suffix}/dispatch/app"
WS_PATH = "/api/ws"
WS_USER_VERSION = 8
WS_HB_INTERVAL_FALLBACK = 145
WS_HANDSHAKE_TIMEOUT = 15
# Reconnect backoff, in seconds, indexed by consecutive failures. The last
# value repeats. A socket that stayed up for more than two minutes resets the
# index, so a nightly router reboot does not leave a 5-minute gap behind.
WS_RECONNECT_DELAYS = (0, 5, 15, 30, 60, 120, 300)
# After replacing the token we close the old socket ourselves; the cloud needs
# a moment to release that session, so the next handshake waits this long.
WS_RECONNECT_GRACE = 3
# A failure that lands inside this window after a self-initiated reconnect is
# the tail of that handover, not an outage - log it at debug instead of warning.
WS_CHURN_WINDOW = 90
# How often the supervisor task wakes up to honour a reconnect request and to
# check for a silent socket. Kept short: aiohttp's own receive timeout proved
# unreliable here, so nothing may depend on it.
WS_FLAG_POLL = 5
# How long the socket may keep replacing the poll with pushes before a real
# HTTP read is forced in. The poll is still the only thing that renews the
# token, refreshes the map and probes for firmware, so it must not starve.
PUSH_POLL_GUARD_SECONDS = 900

# Map refresh
MAP_REFRESH_MINUTES = 30
MAP_HISTORY_NUM = 3
# History endpoint is lightweight; probe it at most every 5 minutes.
MAP_CHECK_SECONDS = 300
# OTA availability check (POST /v2/device/ota/query) is light but has no
# user-visible urgency; probe it at most once per hour.
OTA_CHECK_SECONDS = 3600
# After a failed token renewal, space retries out instead of hammering the
# cloud on every poll cycle. Kept close to the poll interval (180 s): the
# renewal call is already throttled by REFRESH_MIN_INTERVAL, and a long
# cooldown here delays the reauth prompt for no benefit.
RELOGIN_COOLDOWN_SECONDS = 300
# Minimum gap between two token-refresh attempts (protects the cloud from a
# refresh storm when it is unreachable). Poll interval is 180 s, so this only
# suppresses back-to-back attempts from control calls.
REFRESH_MIN_INTERVAL = 120
# Number of consecutive failed poll cycles before the integration raises the
# "re-authentication required" repair issue. A single transient 4001 (the
# cloud answers it while another client holds the session) used to pop the
# prompt immediately, which looked like a random error banner.
REAUTH_AFTER_FAILURES = 3
# v1.4.7: gap between retries when the *first* refresh after a setup/reload
# failed. Home Assistant does not schedule the interval refresh when
# async_config_entry_first_refresh() raises, so without an explicit retry the
# coordinator stopped polling for good - the failure counter stayed at 1, the
# reauth prompt never appeared and every entity froze on its last value.
SETUP_RETRY_SECONDS = 120
# v1.2.11: how long to assume a freshly issued CoolKit access token lives when
# the renewal response does not say. The gateway's documented policy is a
# 30-day access token ("Access Token expires in 30 days... you can use Refresh
# Token to refresh to obtain Access Token instead of logging in again", CoolKit
# v2 API docs; third-party long-running clients renew every 28 days), and the
# first authentication of this account indeed returned exactly 30 days.
#
# This value doubles as the tolerated Home Assistant downtime: the entry keeps
# the token and its expiry on disk, so after a restart the integration only
# needs a token that is still alive. Assuming 1 hour (v1.2.10) meant a downtime
# of over an hour forced a manual reauthentication; 25 days leaves a 5-day
# safety margin under the documented 30 without wasting renewals.
AT_LIFETIME_FALLBACK_SECONDS = 25 * 24 * 3600

# Signing
SIGN_CLIENT_ID = "971d3d280f96"
SIGN_KEY = "okp0be4d645f610f19dc7418c7f473cc"

# Fixed request headers for okplife API
OKP_HEADERS = {
    "app": "okp",
    "client-product": "2",
    "language": "zh-CN",
    "country-id": "37",
    "sup": "4",
    "versionname": "v3.4.0",
    "versioncode": "34000",
    "clienttype": "android",
    "user-agent": "okhttp/4.10.0",
    "timezone": "Asia/Shanghai",
    "system-sdk-version": "32",
}

# Polling
# 3-minute polling: keeps the cloud session usage low. OKP cloud treats a
# same-account client as the only active session, so heavy polling from the
# integration must stay minimal to avoid interfering with the phone app.
DEFAULT_SCAN_INTERVAL = 180
COORD_DATA = "data"

# Vacuum fan speeds (wind power gear)
FAN_QUIET = "quiet"
FAN_STANDARD = "standard"
FAN_STRONG = "strong"
FAN_SPEED_LIST = [FAN_QUIET, FAN_STANDARD, FAN_STRONG]

# Clean modes
MODE_SMART = "smart"
MODE_RANDOM = "random"
MODE_WALL_FOLLOW = "wall_follow"
MODE_SPIRAL = "spiral"
MODE_LIST = [MODE_SMART, MODE_RANDOM, MODE_WALL_FOLLOW, MODE_SPIRAL]

# Mode <-> CoolKit dp mapping (shared by vacuum platform and sensors)
MODE_TO_VALUE = {MODE_SMART: 0, MODE_RANDOM: 1, MODE_WALL_FOLLOW: 2, MODE_SPIRAL: 3}
VALUE_TO_MODE = {v: k for k, v in MODE_TO_VALUE.items()}

# Per-model dp semantics (verified on K5 Ultra). Other models may differ;
# extend this table as devices are tested. The sensor/select/switch platforms
# only create entities whose dp key is present in the device's thing payload.
# sensor key -> required CoolKit dp key
SENSOR_DP_REQUIREMENTS = {
    "work_state": "wstate",
    "clean_mode": "mode",
    "fault_code": "fault",
    "rssi": "rssi",
    "firmware_version": "fwVersion",
    "cleaning_area": "cleaningArea",
    "cleaning_times": "cleaningTimes",
    "carpet_booster": "carpetBooster",
    "battery": "power",
    "dp31": "dp31",
    "last_clean_start": "startUpload",
    "last_clean_end": "endUpload",
    "ui_active": "uiActive",
    "call": "call",
    "timers": "timers",
    "timers_total": "timers",
    # v1.2.0: additional dps observed in the v3.4.0 app capture on K5 Ultra
    # (move = movement state, version = device/software version counter).
    "move": "move",
    "version": "version",
}
# select / switch platforms
SELECT_REQUIRES_DP = "mode"
SWITCH_REQUIRES_DP = "carpetBooster"
