"""Constants for the OKP Cloud vacuum integration."""

from homeassistant.const import Platform

DOMAIN = "okp_cloud"
PLATFORMS = [
    Platform.VACUUM,
    Platform.SENSOR,
    Platform.CAMERA,
    Platform.SELECT,
    Platform.SWITCH,
]

CONF_ACCOUNT = "account"
CONF_PASSWORD = "password"

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
