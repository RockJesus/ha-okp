"""Constants for the OKP Cloud vacuum integration."""

from homeassistant.const import Platform

DOMAIN = "okp_cloud"
PLATFORMS = [Platform.VACUUM, Platform.SENSOR]

CONF_ACCOUNT = "account"
CONF_PASSWORD = "password"

# okplife REST API
API_BASE = "https://api-cn.okplife.com"
API_BASE_ALT = "https://api.okplife.com"
ENDPOINT_LOGIN = "/v5/client/login-with-password"
ENDPOINT_HOME_LIST = "/v2/home/list"
ENDPOINT_DEVICE_LIST = "/v9/home/device-list"
ENDPOINT_DEVICE_DETAIL = "/v5/home/device-detail-info"
ENDPOINT_CK_REFRESH = "/v1/coolkit/refresh-access-token"

# CoolKit (thing cloud) API
CK_BASE = "https://cn-apia.coolkit.cn"
CK_ENDPOINT_THING = "/v2/device/thing"
CK_ENDPOINT_THING_UPDATE = "/v2/device/thing/update"
CK_APP_ID = "fv3LFoaAO65cb5bfaKw6okoHzBVpVX1z"  # x-ck-appid (OKP app)
CK_DOMAIN = "douban"  # domain-name header seen in the OKP app capture

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
DEFAULT_SCAN_INTERVAL = 30
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
