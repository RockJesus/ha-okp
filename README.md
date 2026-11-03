<p align="center">
  <img src="custom_components/okp_cloud/brand/logo.png" alt="OKP" width="128">
</p>

# OKP 扫地机器人（OKP Cloud）

[![GitHub Release](https://img.shields.io/github/v/release/RockJesus/ha-okp?style=flat-square)](https://github.com/RockJesus/ha-okp/releases/latest)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat-square)](https://hacs.xyz/)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.6+-%23049cdb?style=flat-square&logo=home-assistant&logoColor=white)](https://www.home-assistant.io/)
[![Last Commit](https://img.shields.io/github/last-commit/RockJesus/ha-okp?style=flat-square)](https://github.com/RockJesus/ha-okp/commits/main)

通过 **OKP 云账号（用户名 + 密码）** 把 OKP / 乐帆（Lefant）扫地机器人（如 **OKP K5 Ultra**）接入 Home Assistant，无需本地密钥、无需第三方中转。

## ✨ 功能

- 🔐 **用户名 + 密码登录** OKP 云（`api-cn.okplife.com`），自动完成请求签名与令牌管理
- 🏠 自动发现账号下的家庭与扫地机器人设备
- ⚡ **实时推送**：像 App 一样保持一条 CoolKit WebSocket 长连接，机器上报的状态 1 秒内进 HA（清扫中尤其明显）；断线自动重连，连不上就退回轮询，功能不受影响
- 📡 3 分钟状态轮询兜底：电量、清扫状态、工作状态、故障码、信号强度、固件版本、清扫面积/次数、定时任务摘要、最近清扫时间、固件更新检查等
- 🎮 完整控制：开始清扫 / 暂停 / 停止 / 回充 / 三档吸力（安静 · 标准 · 强力）/ 清扫模式（智能 · 随机 · 沿墙 · 螺旋）/ 地毯增压开关
- 🕹️ **手动遥控**：像 App 摇杆一样前后左右点动（5 个按钮），也可用 `okp_cloud.move` 服务按住指定时长或按住不放；松开由集成负责，超时会自动松开
- 🗺️ 清扫地图（camera 实体，PNG 渲染，5 分钟探测 / 30 分钟自动刷新）
- 🔄 CoolKit 令牌过期自动静默刷新；**不自动密码重登**（OKP 云单会话，重登会顶掉手机 App）——令牌彻底失效时自动弹窗重新认证
- 💾 云端离线时保留最后已知状态（实体永不 `unavailable`）

## 📦 安装

### 方式一：HACS（推荐）

1. HACS → 「自定义仓库」→ 添加 `https://github.com/RockJesus/ha-okp`（类别：**集成**）
2. 搜索并安装 **OKP Cloud 扫地机器人**
3. 重启 Home Assistant

### 方式二：手动安装

1. 下载最新 [Release](https://github.com/RockJesus/ha-okp/releases/latest) 源码包
2. 解压出 `custom_components/okp_cloud` 目录，放入 `config/custom_components/`
3. 重启 Home Assistant

## ⚙️ 配置

「设置 → 设备与服务 → 添加集成」→ 搜索 **OKP 扫地机器人**，输入 OKP App 的**账号（手机号）**与**密码**，提交即自动完成登录、家庭与设备发现。

后续若令牌失效可在集成上点「重新认证」，或「重新配置」更换账号。

## 🧹 实体（设备：OKP K5 Ultra）

| 实体 | 类型 | 说明 |
| --- | --- | --- |
| `vacuum.okp_cloud_*` | 扫地机 | 清扫状态 / 电量 / 吸力档位 / 控制 |
| `select.okp_cloud_*_mode` | 选择器 | 清扫模式（智能/随机/沿墙/螺旋，可控制） |
| `switch.okp_cloud_*_carpet_booster` | 开关 | 地毯增压（可控制） |
| `sensor.okp_cloud_*_work_state` | 传感器 | 工作状态（清扫/回充/暂停/待机） |
| `sensor.okp_cloud_*_clean_mode` | 传感器 | 清扫模式（smart/random/wall_follow/spiral） |
| `sensor.okp_cloud_*_rssi` | 传感器 | 信号强度（dBm，诊断） |
| `sensor.okp_cloud_*_fault_code` | 传感器 | 故障码（诊断） |
| `sensor.okp_cloud_*_firmware_version` | 传感器 | 固件版本（诊断） |
| `sensor.okp_cloud_*_cleaning_area` | 传感器 | 清扫面积 |
| `sensor.okp_cloud_*_cleaning_times` | 传感器 | 清扫次数 |
| `sensor.okp_cloud_*_battery` | 传感器 | 电量（%） |
| `sensor.okp_cloud_*_dp31` | 传感器 | 数据点 dp31（诊断） |
| `sensor.okp_cloud_*_last_clean_start` | 传感器 | 上次清扫开始（诊断） |
| `sensor.okp_cloud_*_last_clean_end` | 传感器 | 上次清扫结束（诊断） |
| `sensor.okp_cloud_*_ui_active` | 传感器 | 界面活跃值（诊断） |
| `sensor.okp_cloud_*_call` | 传感器 | 呼叫计数（诊断） |
| `sensor.okp_cloud_*_timers` | 传感器 | 定时任务摘要（诊断） |
| `sensor.okp_cloud_*_online` | 传感器 | 在线状态（诊断） |
| `camera.okp_cloud_*_cleaning_map` | 摄像头 | 清扫地图（PNG 渲染） |
| `sensor.okp_cloud_*_firmware_update` | 传感器 | 固件更新检查（OTA，有新版时显示目标版本，否则「已是最新」） |
| `sensor.okp_cloud_*_realtime` | 传感器 | 实时推送通道状态（诊断，见下） |
| `button.okp_cloud_*_move_*` | 按钮 | 手动遥控：前进 / 后退 / 左转 / 右转 / 松开（每次 0.5 秒点动） |

> 扫地机实体还附带扩展属性：`work_state`、`clean_mode`、`fault_code`、`rssi`、`firmware_version`、`cleaning_area`、`cleaning_times`、`carpet_booster`、`online`、`last_error`。

## ⚡ 实时推送

集成会像 App 一样，向云端的区域节点开一条 WebSocket 长连接（`dispatch/app` → `wss://…/api/ws` → `userOnline`），
设备每次上报的 dp 变化立刻合并进实体状态，**不再等 3 分钟轮询**。这条通道是只读的——所有控制仍然走
HTTP 接口，所以它不可能把机器人置成 App 里做不出来的状态。

3 分钟轮询并未取消，仍然是兜底：连接断了、被路由器掐了、账号会话异常，都只是"慢回 3 分钟"，实体照常工作。
连续推送时也至少每 15 分钟强制做一次 HTTP 读取，保证令牌续期、地图刷新、OTA 检查不会饿死。

`sensor.okp_cloud_*_realtime` 会显示当前通道状态：`connected` 已连接 / `connecting` 连接中 /
`disconnected` 断线重连中 / `error` 连接失败（仍在轮询） / `disabled` 未启用。属性里有
`host`（当前节点）、`device_pushes`（收到的设备推送条数）、`last_push_at`、`last_poll_at`、`last_error`。

如果测试发现这条连接和手机 App 抢会话（打开 App 后推送变 `error` 或反复重连），在
**「设置 → 设备与服务 → OKP 扫地机器人 → 配置」** 里关掉「启用实时推送」即可，其他功能完全不变。

## 🕹️ 手动遥控

App 的摇杆在协议层就是按压/松开两件事：按住某个方向时写 `{"move": 0..3}`，手指抬起写 `{"move": 4}`。
集成把它拆成两层，方便点按也方便做真正的摇杆：

- **五个按钮**（`button.okp_cloud_*_move_forward` 等）：每次点击 = 0.5 秒点动，适合「把它从餐桌底下挪出来」这种微调
- **`okp_cloud.move` 服务**：`direction` 选方向、`duration` 选按住多久（上限 10 秒）；`duration: 0` 表示一直按住，
  直到再发一次 `direction: stop`

```yaml
# 一次 1.5 秒的前进
action: okp_cloud.move
data:
  direction: forward
  duration: 1.5

# 摇杆式：按住走、松手停（例如按下时发这个，抬起时发 direction: stop）
action: okp_cloud.move
data:
  direction: left
  duration: 0
```

**松开这件事集成会兜底**：给了 `duration` 就一定会在结束时（包括服务调用被中断）发 `{"move": 4}`；
`duration: 0` 的按住状态也有关机保护——超过 10 秒没人松开，集成会自动松开并在日志里提醒一句，
所以不会出现「卡片关了、机器还在跑」的情况。同一时刻只允许一路按压，重入的调用会被串行化。

关于方向值：`0/1/2/3` 对应前后左右是**厂商约定**，尚未在真机上核对。如果你发现某个按钮方向不对，
先用 `value:` 传原始值试（`0`–`3` 方向、`4` 松开），确认后告诉我，我把映射表改掉。

怎么确认「到底发出去的是什么」：`move` 是**命令位**，设备执行但不回报——抓包里只有 App 写的
`userAgent:"app"` 帧，从来没有设备回传 `move`，所以 `sensor.okp_cloud_*_movement_state` 基本恒为 `4`。
集成把最近一次发出去的命令放在扫地机实体的 `remote_move` 属性里（`value` / `direction` / `at`），
点一下「前进」再去看它，就知道实际发的是 `0`；配合机器人的实际动作就能校准映射。

## 🎛️ 支持设备

- **OKP K5 Ultra**（实测，CoolKit / ThingClips 云）
- 其他 OKP / 乐帆云账号下的扫地机理论上兼容（协议相同）

## 🔧 技术说明（协议逆向摘要）

<details>
<summary>点击展开</summary>

- 登录：`POST /v5/client/login-with-password`（`password` + `account`）
- 签名：`MD5(client-id=...&timestamp=<ms>&key=...)`——自 APK `TokenInterceptor` 指令级逆向，43/43 个抓包请求复算命中
- 设备：`/v2/home/list` → `/v9/home/device-list` → `/v5/home/device-detail-info`
- 令牌：`GET /v1/coolkit/get-user-info`（okplife，带签名头）换取 CoolKit `at`/`rt`/`apikey`；
  续期走 `POST cn-apia.coolkit.cn/v2/user/refresh`（body `{"rt":…}`，且**必须**带 `Authorization: Bearer <hex>`）
- 状态：`POST cn-apia.coolkit.cn/v2/device/thing`（body `{"thingList":[…]}`）
- 控制：`POST cn-apia.coolkit.cn/v2/device/thing/status`（body `{"type":1,"id":…,"params":{…}}`）
- 实时：`GET cn-dispa.coolkit.cn/dispatch/app` 取节点 → `wss://<domain>:443/api/ws` →
  发 `{"action":"userOnline","apikey","appid","at","version":8}` → 回 `{"error":0,"config":{"hbInterval":145}}` →
  约每 72 秒发文本 `ping` 收 `pong`；设备上报为 `{"action":"update","userAgent":"device","params":{…}}`

</details>

## ⚠️ 已知限制

- **回充 = 停止清扫**（CoolKit 无独立回充 dp）；若你的机型不回充，请抓包一次「回充」动作反馈后补充
- **暂停 = 停止清扫**（`sweep=0`），与 App 行为一致
- 密码保存在 HA 配置存储（`.storage/`）中，仅用于首次配置/重新认证时登录；运行中不使用密码

## 📝 更新日志

- v1.6.5（2026-11-03）：**修掉 v1.6.3 引入的崩溃**。v1.6.3 给 `refresh_session` 加诊断字段时用了 `CONF_ACCOUNT` 却没有从 `const` 导入，导致该服务每次调用都抛 `name 'CONF_ACCOUNT' is not defined`。更糟的是这掩盖了真相：因服务报错，一直读不到 `coordinator_count`，误判成「HA 上跑的还是没有这些字段的旧版本」。同时查清了「版本号说谎」的问题——`update` 实体长期显示 `installed = v1.6.2`，实际运行的却是 v1.5.5/1.6.0 的代码，原因是 HACS 走 `ghrp2.hacs.vip` 镜像下载，单文件超时 60 秒即告失败（日志 `Tries left 14`），安装从未真正落地。现已在 HA 主机上完成 v1.6.4 的真实安装并重启验证

- v1.6.4（2026-11-03）：**修掉副账号「登录成功但 0 个设备」的真正根因**。v1.6.2 解决的是实体 ID 撞车（第二份被丢弃），v1.6.3 加的诊断证明副账号条目**连协调器都是 0 个**——问题不在实体层，在设备发现层。根因：配置流用 `GET /v2/home/list` + `GET /v9/home/device-list` 发现设备，而这条 **OKP 云接口是按 home 且只返回「本账号自有」设备**；别人分享过来的机器（CoolKit 里 `itemType = 2`）根本不在这个列表里，于是 `_validate_login` 拿到空列表、条目却照样创建，表现为「登录成功、什么都没出现」。这一版：① 发现流程在 OKP 列表之外**追加 CoolKit `GET /v2/device/thing`**（账号维度、含 `itemType 2` 分享设备），按 dp 特征（`ROBOT_DP_HINTS`）过滤出机器人，与 OKP 结果按 `third_dev_id` 去重合并；② 副账号即便没有任何 home 也能成立（`home_id` 允许为空）；③ `no_device` 报错改成可执行的三步自检（主账号是否已分享、分享是否生效、副账号 App 里能否看到）；④ 顺带修掉 v1.6.3 发布物里 `manifest.json` 被写成 0 字节导致 HACS 无法安装的问题

- v1.6.3（2026-11-03）：**增加「条目自己到底拿到了什么」的诊断**。v1.6.2 修好 unique_id 撞车后现场确认：两个条目都 `session_state = rt`、`realtime = connected`、`error = None`，但 `entity_registry` 里 okp_cloud 的 34 个实体**全部挂在主账号条目下，副账号条目 0 个**。也就是说 `loaded` 并不等于「有设备」——一个条目可能加载成功却没有任何协调器，而界面和旧版诊断都看不出来。这一版给 `refresh_session` 的每条返回加上 `title` / `account` / `is_shared_entry` / `entity_scope` / `coordinator_count` / `devices[]`（含 `has_coordinator`），一眼能定位是「没扫到设备」还是「扫到了但没建协调器」。同时修正一处早先文档的错误描述：`vacuum.xiao_du_*` 实体属于**小度插件**，与 OKP 无关

- v1.6.2（2026-11-03）：**修掉「多账号登录后不显示设备」**。用户按 v1.6.1 指南用副账号登录后，两个条目都 `loaded`、都扫到了同一台 K5 Ultra，但**第二个条目的实体一个都没出现**，日志刷满 `Platform okp_cloud does not generate unique IDs. ID okp_cloud_100258a68a already exists - ignoring vacuum.sao_di_ji_qi_ren`。根因：实体 `unique_id` 只由 CoolKit 设备 ID 拼成（`okp_cloud_<device_id>[_suffix]`），而同一台设备在主账号和副账号（或迁移期间的旧条目）里会出现两次 —— HA 按 unique_id 去重，第二份直接被丢弃，且**不报错到界面**，只在日志里留一行。这一版：① 新增 `const.entity_scope(entry)` —— **按条目创建时间排序，最早的那个条目保持原有 ID 不变**（已有安装的实体 ID、自动化、仪表盘全都不受影响），其余条目追加自己 `entry_id` 的 6 位后缀；② 六个平台（vacuum / sensor / select / switch / button / camera）共 12 个实体的 unique_id 全部接入；③ 同一台设备因此在两个账号下各有独立的实体组（如 `vacuum.sao_di_ji_qi_ren` 与 `vacuum.sao_di_ji_qi_ren_XXXXXX`），可同时在线、互不覆盖

- v1.6.1（2026-11-03）：**「一个账号两处登录」给出可执行答案**。用户条件是只有一个手机号。查证结果：① CoolKit 注册接口「手机号和邮箱二选一」，没有绑定/叠加入口；OKP 登录接口对手机号与邮箱是两条独立路径（都返回「该帐号不存在」而非格式错误）——**同一手机号无法派出第二个账号**。② 但 OKP 官方 FAQ 明确支持**邮箱注册**且不需要第二个手机号（"create a new account using your email address"）。③ 因此可行路径是「主账号留在手机 App + 用邮箱注册副账号给集成」：OKP App 里把机器人分享给副邮箱 → HA 选择「共享账号」入口登录。这一版把这三步直接写进配置表单的说明文案里（中英双语），并新增 `docs/two-accounts-guide.md` 逐步操作文档，含权限勾选说明与旧条目处理方式

- v1.6.0（2026-11-03）：**新设备免密码接入：`okp_cloud.rescan_devices` 服务**。此前的限制：多设备支持本身是有的（v1.1.9 起一个账号下每台机器人一个独立协调器，K2/K3/K5/L 系列通用，实体按设备实际携带的 dp 动态创建、没有机型白名单），但**在 App 里新买/新接入一台机器人后，集成只有在重新验证（输密码）时才会扫到它**——设备列表只在配置流里重建。这一版新增 `rescan_devices` 服务：① 优先走 CoolKit `GET /v2/device/thing` 全量清单——只需要 30 天有效的 CoolKit 令牌，完全不依赖几小时就过期的 OKP 登录令牌，也**能看到分享给本账号的设备**（itemType 2，v1.5.5 共享账号路线由此完整可用）；② 机器人识别按 dp 特征（workState / sweep / cleaningArea / startUpload 等），不会给非扫地机设备误建吸尘器实体；③ 新设备并入配置条目后自动重载集成，实体即刻出现；④ 云端已消失的设备**不会**被自动删除——移除硬件应当是主动操作，不能是网络抖动的副作用。返回值含 source / discovered / added / reloaded

- v1.5.5（2026-11-03）：**找到厂商文档，给出「App 与集成同时登录」的最终答案**。这次不再靠实测反推：CoolKit 官方文档《开发文档_v2 → AT 和 RT 说明》原文写着——「同一个帐号在同一个应用下不能同时登录，每登录一次会重新刷新 access token，让前面登录的用户 access token 失效，使其被迫下线」，FAQ 也直接写「不支持多次登录同一帐号」。集成用的正是 OKP App 自己的 `appid`（`fv3LFoaAO65cb5bfaKw6okoHzBVpVX1z` / `domain-name: douban`），云端视角里它和手机 App 是同一个应用下的两次登录，**必然互踢**；而且会话被顶掉时**连刷新令牌一起作废**（v1.5.4 的 `refresh_attempts` 三条候选全 401 就是证据），所以「用 rt 悄悄救回来」这条路在这种场景下根本不存在。这一版做三件事：① 实时推送默认改为**开启**（`CONF_REALTIME_DEFAULT = True`）——v1.4.6 把它关掉的判断是错的：弄坏会话的是 App 登录，不是 socket；而长连接恰恰是让会话「保持在用」的唯一手段（实测 4 小时零续期、零重连、零认证失败）。② 新增 `session_end_reason`（`refresh_session` 返回值 + 会话传感器 `end_reason` / `end_reason_hint`）：把「会话死了」细分为 `session_superseded`（被同 appid 的另一次登录顶掉，重试无意义）与 `refresh_token_rejected`（rt 自然过期），并直接给出该怎么做，不用再猜。③ 文档 `docs/multi-client-limit.md` 记录三条路线：换 appid（普通人拿不到）、伪装成设备（拿不到账号级数据）、**设备分享给第二个账号**（官方推荐做法，唯一可行）——这才是「App 和集成同时可用」的真正实现方式。详见该文档

- v1.5.4（2026-11-02）：**「重启就失效」的真正原因——续期请求被过期的 at 拖累**。实测：21:21 会话正常（`rt`，29 天），21:27 重启 HA，启动那一秒（21:27:41）就报 `401 cannot found access token info`，App 全程没登录。关键在续期接口的调用方式：`POST /v2/user/refresh` 必须带 `Authorization: Bearer <at>`，而代码先把 **at** 作为候选头发出去——重启后旧 at 已被云端作废，网关在**检查请求头这一步**就返回 401，body 里的 rt 根本没被看到。于是日志写成「rt 也被拒」，实际是「rt 没轮到」。这一版：① 候选顺序改为 **rt 优先**（`Bearer <rt>` → `Bearer <at>` → 不带 Authorization），让真正的续期凭据先说话；② 新增 `last_refresh_attempts`，把每个候选的真实返回逐条记下（如 `refresh token -> ok`、`access token -> 401 ...`），并在 `refresh_session` 返回值里输出 `refresh_attempts`——从此「rt 真的死了（402/403）」与「rt 压根没被检查」可以一眼区分；③ 401 仍然保留 rt 不清空（原有正确逻辑不变）。这是验证性版本：部署后的 `refresh_attempts` 会直接告诉我们 rt 到底还有没有效

- v1.5.3（2026-11-02）：**找到并修掉「引入实时推送后会话就不稳」的真正原因**。现象：v1.3.3 加入实时推送之前，会话能稳定跑很久；加入之后，重启或过一段时间就 `401 cannot found access token info`。根因不是令牌存坏了，而是**实时 socket 与轮询在互相抢同一个单会话 slot**：① CoolKit 的 `userOnline` 是**单会话登记**——一个账号同时只允许一个在线客户端，握手用的那个 at 就是"当前会话"；② 但 `ensure_coolkit_token()` 会在 token 年龄超 1 小时或临近过期时续期，而**每次续期都会轮换 at**；③ socket 握完手后，轮询一续期，at 就变了 → socket 手里的 at 成了"旧会话"；④ socket 察觉 token 变了就重连，重连的 `userOnline` 又把刚续出来的**新 at** 顶掉 → 轮询 401 → 再续期 → 再被顶。这个循环跑几轮后，云端把整个会话一起销毁，本地 at/rt 全成孤儿，就是实测到的 `rt 也被拒`。这一版：① 新增 `api.session_socket_at`（会话归属标记）：socket 握手成功后登记"我在用这个 at"，断连时按值比较后释放；② `ensure_coolkit_token()` 增加闸门——**socket 持有会话期间一律不续期**，避免把 token 从 socket 脚下抽走；③ socket 重连前不再无条件续期（这正是旧代码自伤的地方）；④ 到期前 15 分钟由 **socket 主动交还会话**（`WS_HANDOVER_SECONDS`），轮询续期、等待 5 分钟后再重连，让续期和登记错开；⑤ `refresh_session` 的 `force` 不再强行轮换：socket 在线时直接返回提示，避免手动操作把会话打断；⑥ 心跳发送失败不再静默退出，改为记日志（原来会让 socket 变哑且看起来"健康"）。诊断新增 `session_held_by_socket` 字段，可直接看出当前是 socket 还是轮询在持有会话

- v1.5.2（2026-11-02）：**修掉 v1.5.1 的导入遗漏**。现场日志暴露了 `OKP first refresh failed (retrying every 120s): name 'CK_ENDPOINT_USER_LOGOUT' is not defined`：新增的释放接口常量只定义了、没在 `api.py` 的导入块里引入，导致 v1.5.1 的「释放 + 续期」探查在第一次轮询就抛 `NameError`，整轮读取直接失败（诊断显示 `session_origin = unknown`、`realtime = null`）。这一版：① 补上 `CK_ENDPOINT_USER_LOGOUT` 的导入；② 把探查整体加固成**纯尽力而为**——释放调用即使抛出意料之外的异常也只记 debug，绝不中断后面的续期与认证失败计数（否则 reauth 永远不会触发，条目会一直卡在 unknown）；③ 版本号按「遇 10 进 1」规则推进到 1.5.2

- v1.5.1（2026-11-02）：**给「会话是谁拿走的」提供可验证证据**。v1.5.0 假设「重启丢会话」是集成写坏了令牌，但现场证据（rt 明明存在、却被云端以 `401 cannot found access token info` 拒掉）说明更可能是**会话被别人顶掉**。这一版不猜，直接让集成把判定过程记录下来：① 新增会话来源字段 `coolkit_session_origin`（`reauth-password` = 用密码登录换来的，代价是 App 被挤掉；`rt-renewal` = 用刷新令牌续的，谁都碰不到；`okplife` = 走 OKP 登录令牌续的）与 `coolkit_session_started_at`，随令牌一起持久化，重启后仍可追溯；② 遇到 `401` 时先做一次「释放 + 续期」探查：调用 `POST /v2/user/logout` 主动释放自己的旧 access token（云端通常「新会话顶掉旧会话」，主动释放后才接受续期），再用 rt 续期；**能续成功说明旧 token 只是被撤销、会话没被抢**，直接恢复轮询、不弹重新验证；续期也被拒说明会话确实被抢走，日志明确写 `the session was taken over, not lost locally`；③ `refresh_session` 服务返回值新增 `session_origin` / `session_started_at` / `last_rt_probe_result`，不用翻日志就能判断归属

- v1.5.0（2026-11-02）：**修掉「重新验证后一切正常、一重启就失效」**。现象：19:18 重新验证成功，`cloud_session = rt`、电量/在线全部正常；19:26 重启 HA，26 秒内就报 `coolkit refresh failed: 401 cannot found access token info`，回到 `stale`。根因是**令牌只写了一部分进配置条目**：`config_flow._entry_data()` 手挑了几个 key（`coolkit_at` / `coolkit_at_expire` / `coolkit_rt` ...），漏了 `coolkit_at_lifetime`、`coolkit_at_expire_inferred` 和 v1.4.11 新增的 rt 时间戳；`async_step_reauth` 的静默恢复分支也是手拼字段。这类「半套令牌」条目能加载、能跑一次，重启后恢复出来的会话就被云端拒绝。这一版：① 新增 `const.persisted_token_fields(api)` 作为**唯一**写入入口，coordinator 轮询、配置流程、重新验证静默恢复、启动升级路径四处全部改用它，杜绝字段漂移；② 启动自检：从条目恢复时若发现「有 rt 但没有 at 过期时间」这类残缺组合，先打日志说清楚，再用 rt 续期一次后才进轮询，不再带着来路不明的会话开跑；③ 启动时以 debug 打出 `OKP session restored from the config entry: {...}`，下次再出问题能直接看到恢复到了什么

- v1.4.11（2026-11-02）：**别让「看一眼」把会话看没了**。部署 v1.4.10 时用 `okp_cloud.refresh_session` 做验证，结果 CoolKit 云端在续期时轮换了刷新令牌（rt）并作废旧令牌，几小时后两条令牌链同时失效（`coolkit refresh failed: 401 cannot found access token info` + `4001 请先登录`），只能重新输密码。这一版：① `refresh_session` 改为**默认只读**（`mode: report`，不发任何网络请求、不消耗令牌），要真续期必须显式传 `force: true`；② 认证失败计数分级：rt 已被云端拒绝（已清空）按满速计数，rt 仍在的临时失败半速计数——连续三次云端抖动不再弹密码框（弹一次就丢一次 App 会话）；③ 新增 rt 生命周期追踪：`coolkit_rt_issued_at` / `coolkit_rt_rejected_at` / `coolkit_rt_reject_count`，持久化到配置条目，下次会话失效能直接看出是哪个时间点被谁消耗

- v1.4.10（2026-11-02）：**清扫模式选择器改中文**。`select.*_clean_mode` 的选项由 `smart / random / wall_follow / spiral` 改为 **智能 / 随机 / 沿边 / 螺旋**。① 状态机与传感器（`sensor.*_clean_mode`、定时任务的 `mode` 提示）内部仍用英文 code，避免破坏已有自动化与历史统计；② `select.select_option` 同时接受中文标签和旧的英文值，老脚本调用不会报 `unknown clean mode`；③ 增加 `RestoreEntity` 兼容：升级后重启时把 `.storage` 里恢复的旧英文状态映射为中文，避免首个轮询周期前显示 `unknown`

- v1.4.9（2026-11-02）：**App 登录与集成会话解耦**。① `ensure_coolkit_token`：只要 CoolKit 刷新令牌（rt）还在，rt 刷新就是唯一续期路径——rt 临时失败（网络抖动/云端 5xx）不再回退到 okplife 路由；此前 App 登录踢掉 OKP 令牌后，okplife 回退必然抛认证错误并推进 reauth 计数，逼用户输密码（密码登录又把 App 踢回去，两边互踢的恶性循环）。rt 被云端明确拒绝（402/403，此时 rt 已被清空）才回退 okplife。② reauth 流程静默自愈：进入密码表单前，先用配置条目里存的 rt 尝试续期一次，成功则直接更新令牌并结束 reauth——App 登录顶掉 OKP 令牌这种最常见场景下，**无需输密码、App 会话不受任何影响**；只有 rt 也死了才出现密码表单。③ reauth 表单文案明确提示「提交密码会临时挤掉 App 登录」

- v1.4.8（2026-11-02）：**热修复 v1.4.7 引入的卸载崩溃**。v1.4.7 用 `entry.async_on_unload(task.cancel)` 取消重试任务，而 `Task.cancel()` 返回 `True`；Home Assistant 把 unload 回调的非 `None` 返回值当成待等待的协程，于是卸载报 `a coroutine was expected, got True`，条目卡在 `failed_unload`——重新验证完成后无法重载、所有实体变 `unavailable`。现改为显式 `def _cancel_retry_task(): task.cancel()`（返回 `None`）

- v1.4.7（2026-11-02）：**修复「首次刷新失败后集成静默瘫痪」**。场景：HA 重启时云端会话已失效（App 登录顶号，CoolKit 返回 `401: cannot found access token info`、okplife 返回 `4001: 请先登录`），`async_config_entry_first_refresh()` 抛错，而 Home Assistant 在这种情况下**不会**排下一次定时刷新——于是轮询彻底停摆：`last_poll_at` 冻在启动那一刻、`auth_failures` 永远停在 1、永远到不了第 3 次，「重新验证」提示永不出现，所有实体卡在最后一个值，只能手动重载（重载也只是重复同一个死循环）。现在：① 首次刷新失败后启动内部重试循环（每 120 秒一次，直到有轮询成功为止，条目卸载时自动取消），轮询恢复后自动交回定时器；② 首次刷新若因**凭据**失败，直接弹出重新验证提示（不再等 3 个永远不会到来的周期）；③ 日志把「will retry on poll」改成真实的「retrying every 120s」

- v1.4.6（2026-11-02）：**实时推送默认关闭**。真机验证坐实厂商云端对每个用户只允许一个「App 会话」：集成 WebSocket 首次握手成功并收到推送后，打开 OKP App 即被踢下线，之后每次重连都被拒（`handshake rejected: 406 Authentication Failed`），杀掉 App 也不恢复；且 App 登录会连带作废集成的 OKP 令牌链（`4001: 请先登录`，与 v1.2.0 抓包结论一致）。HTTP 轮询全程不受影响（设计兜底）。现在实时推送默认 off，想要秒级刷新的用户可在「配置 → 启用实时推送」显式打开并自行承担与 App 的互踢；已显式打开的存量条目需要手动关一次（存储值优先于默认值）

- v1.4.5（2026-11-02）：按酷宅官方开放文档（`CoolKit-Technologies/eWeLink-API`）对照后修三处。① **读路径 403 不再误杀令牌**：官方错误码表 `401`=令牌被顶号、`402`=令牌过期、`403`=找不到接口（路由/权限问题）；此前 `get_thing_state`／`_ck_get`／`query_ota` 三个读接口收到 403 也清除令牌并触发重登录，一旦某个云端端点下线/改名就会把还活着的会话搞挂，现在与写入路径一致仅对 401/402 标记令牌失效，403 作为普通错误记录。② **处理 `sysmsg` 设备上下线推送**：官方 WS 协议含 `{"action":"sysmsg","params":{"online":false}}` 上下线通知，此前只认 `update` 帧，设备离线要等最多 180 秒轮询才能发现；现在收到 sysmsg 即时更新在线标志，连接传感器秒级反应（实体本体仍保持 available 保留最后状态，与既有设计一致）。③ **握手 nonce 对齐官方要求**：文档要求 `nonce` 必填、8 位字母数字随机数，此前沿用抓包里的空串，现改为随机生成，防服务端日后收紧校验

- v1.4.4（2026-11-01）：自动松开后立刻回读一次状态。实测按住不放时看门狗确实在 12 秒左右松开（日志 `OKP manual move still held after 10.0s; releasing automatically`），但因为实体属性是「上次写状态」的快照，界面上仍显示「按住中」，差点误判成没生效。现在松开后 1.5 秒补一次读取，`remote_move` 立刻变回 `released`

- v1.4.3（2026-11-01）：把「遥控发出去的是什么」暴露出来。查抓包确认 `move` 是**命令位**——设备执行但不回报（只有 App 写的 `userAgent:"app"` 帧，从没有设备回传），所以 `sensor.*_movement_state` 恒为 `4`，光看它无法判断命令有没有生效。扫地机实体新增 `remote_move` 属性（`value` / `direction` / `at`），反映集成最后一次发出的命令，用于校准 0/1/2/3 与前后左右的对应关系

- v1.4.2（2026-11-01）：**手动遥控**。App 的摇杆在协议层是「按住写 `move=0..3`、松手写 `move=4`」，这一版把它做成两层：五个点动按钮（前进/后退/左转/右转/松开，每次 0.5 秒）和 `okp_cloud.move` 服务（`direction` + `duration`，`duration: 0` = 按住不放，直到 `direction: stop`）。安全性上做了三件事：按住必配对松开（服务调用被取消也会发 `{"move": 4}`）、按住超 10 秒自动松开、同一时刻只允许一路按压（重入串行化）；条目卸载时会主动松开，避免「重载之后机器还在跑」。方向值 `0..3` 与前后左右是厂商约定、尚未真机核对，服务额外支持 `value` 直接传原始 dp 便于校准，`sensor.okp_cloud_*_move` 可对照设备回报值

- v1.4.1（2026-11-01）：实时推送传感器改为**实时刷新**。实体属性是上次协调器更新时的快照，排查时读到的 `connected_since` / `reconnect_calls` / `read_iterations` 全是旧值（差点把「已经重连成功」误判成「没重连」）。现在通道状态一变就通知实体重写状态
- v1.4.0（2026-11-01）：实时通道改用「读任务 + 监督任务」结构，彻底摆脱 aiohttp 的关闭/超时语义。实测证据是 `read_iterations` 一直停在 1 —— `ws.receive(timeout=10)` 的超时根本没触发，读循环一直卡在那次 `receive()` 里，于是「续期后重连」只是把标志位设上、没人来消费。现在另起一个监督任务每 5 秒醒一次：看到重连请求就取消读任务、阻塞超时也由它判定（`hbInterval` 内没有任何报文才算掉线）。实测续期后 `reconnect_calls: 1`、`connected_since` 前滚、`reconnects` 递增，日志无告警
- v1.3.9（2026-11-01）：给实时通道补观测字段 `reconnect_calls`（收到几次重连请求）与 `read_iterations`（读循环跑了多少轮），用来区分「请求没送到」和「读循环卡住」。同时把 `reconnect_pending` 从内部状态暴露到传感器属性里
- v1.3.8（2026-11-01）：把「换令牌后撞车」这件事处理干净。v1.3.7 让重连真正生效后，实测发现紧接着的握手会被云端关一次（旧会话还没释放完），日志又多一条看起来像故障的警告。现在主动重连后先等 3 秒再握手；并且主动重连后 90 秒内的失败只写 debug（属于交接尾巴，不是掉线），超过窗口才升级为警告
- v1.3.7（2026-11-01）：修掉「续期后其实没重连」。实测发现从另一个任务调用 `ws.close()` 时，aiohttp 会让 close 与挂起的 `receive()` 互相等待，结果 socket 一直没关、令牌续期后仍用旧令牌，`connected_since` 和 `reconnects` 都不动。现在改为读循环每 2~10 秒自查一次「是否要求重连」，由持有 socket 的任务自己退出并关闭（顺带保留心跳超时判定），重连不再依赖 aiohttp 的关闭语义。新增诊断属性 `socket_open`，并把 `reconnect_pending` 一起暴露出来
- v1.3.6（2026-11-01）：v1.3.5 的降噪没打到位。实测发现从另一个任务关 socket 时，挂起的 `receive()` 有时不是返回 CLOSE 帧而是抛 `ConnectionResetError`，于是「自己关的」仍被记成 `socket closed by the cloud` 警告。现在整个读循环外统一判断「是不是我们主动重连」，无论异常类型都不再误报；顺带修掉关旧连接时可能误清新连接的竞态
- v1.3.5（2026-11-01）：日志降噪。令牌续期后集成会主动断开旧连接再握手，这次「自己关的」此前被记成 `OKP realtime unavailable (socket closed by the cloud)` 警告，看起来像云端把连接踢了。现在区分主动重连与云端断开，前者只写 debug，界面状态也直接回到 `disconnected → connecting → connected`，不再出现误导性告警
- v1.3.4（2026-11-01）：修掉 v1.3.3 引入的一个真问题。v1.3.3 给配置条目加了「选项变更即重载」监听，但令牌续期也会写 `entry.data`，于是每次续期都触发一次整体重载；更糟的是重载会替换 `hass.data[DOMAIN]`，而 `okp_cloud.refresh_session` 正在遍历这个字典 —— 实测该服务直接报 `dictionary changed size during iteration`。现在监听只在「选项说要开」与「确实有连接在跑」不一致时才重载，服务也改为遍历快照。实测 `refresh_session` 恢复正常，返回 `refreshed_by: rt` 且 `realtime: connected`
- v1.3.3（2026-11-01）：**接入和 App 一样的 WebSocket 实时推送**。此前所有实体都靠 180 秒轮询，清扫过程中状态最多晚 3 分钟才反映到 HA；现在按抓包还原的协议（`dispatch/app` 取节点 → `wss://<domain>/api/ws` → `userOnline` 握手 → 每 72 秒 `ping`/`pong` → 设备 `update` 帧）开一条长连接，设备已上报的 dp 变化秒级合并进实体。设计上只读、只做加速：控制仍走 HTTP，轮询保留做兜底与令牌/地图/OTA 维护，连续推送时也至少每 15 分钟强读一次；握手失败按 0/5/15/30/60/120/300 秒退避重连，失败只在日志里说一次。新增诊断传感器 `sensor.okp_cloud_*_realtime`（状态 + `host`/`device_pushes`/`last_push_at`/`last_poll_at`/`last_error`），以及「配置」里的**启用实时推送**开关（万一与手机 App 抢会话可一键退回纯轮询，无需删除集成）。`refresh_session` 服务响应新增 `realtime` 字段，令牌续期后会主动重连以换用新令牌。顺带修正 README 技术说明里过时的控制端点（`thing/update` → `thing/status`）与令牌获取路径（`refresh-access-token` → `get-user-info` → `user/refresh`）
- v1.3.2（2026-11-01）：修掉「控制完要等 3 分钟界面才变」的体验问题。各实体读的都是轮询缓存，而云端回显设备状态有几秒延迟，写完立刻读只会读到旧值，于是 `vacuum.set_fan_speed`／`switch` 之类操作后界面长时间不动（`vacuum` 平台此前压根没有触发刷新，只能等下一轮 180 秒轮询）。现在所有控制动作统一走 `coordinator.async_schedule_refresh()`：写完安排两次延迟回读（约 4 秒、12 秒），既不会读太早，也不用等整轮轮询。实测：写 `quiet` 后约 15 秒 `fan_speed` 已变为 `quiet`，地毯增压同样能即时回读
- v1.3.1（2026-11-01）：给地图相机关联诊断属性 `map_id` / `map_updated_at` / `last_error`。地图出问题时相机只会默默继续给旧图，界面上看不出这张图是哪一次清扫的、是不是已经过期，现在能直接确认（`map_id` 是实际命中的上传 id，`last_error` 会写出 `405 NoSuchKey` 这类原因）。同时修正 v1.3.0 日志里两处过度表述：地图 id 与历史 `from` 单位这两条，实测原本也能正常工作，改动属于「与 App 行为完全对齐 + 提高地图新鲜度」，不是修复既有故障
- v1.3.0（2026-11-01）：按抓到的 App 全功能 HAR（Reqable，v3.4.0）逐条比对后补强。**修复**：① `vacuum.stop` 不再写 `switch: 0` —— App 全程把 `switch` 保持为 1，它是整机电源态，写 0 有把机器人关机、之后云控彻底失联的风险，现在与 App 一致只发 `sweep: 0`；② 地图取图改为**上传 id 优先**（`startUpload`/`endUpload`，如 `015c`），`cleaningId`（如 `0125`）兜底 —— App 只按上传 id 取图，而上传 id 是按次生成的，最近一次常常还没传完就返回 `405 NoSuchKey`。现在按「新→旧」依次尝试、自动跳过没准备好的那次（实测本账号两种 id 都能出图，属于对齐 App + 提高新鲜度，不是原有故障）；③ 历史接口的 `from` 改为**微秒**，与 App 的 16 位时间戳一致（两种单位服务端都接受，改后与 App 行为完全相同）。**新增**：④ 开关「地毯检测」（`dp31`）—— 厂商设备详情里的功能名就是 `carpet_detection_switch`，之前只做成诊断传感器，App 里它是个正常开关；⑤ 按钮「查找机器人」（写 `call: 1`，机器响铃）；⑥ 服务 `okp_cloud.set_timer`（按 `mId` 启停一条定时任务，先重读整组再改单条并回读校验，不会覆盖 App 里新增/删除的任务）；⑦ 定时任务传感器的 `timers` 属性列出每条任务的 `mId`／周期／模式／吸力，供上面的服务直接引用（已验证：`wind` 枚举 0/1/2、`mode` 枚举 `smart/random/wall_follow/spiral` 与集成原有映射一致）
- v1.2.12（2026-11-01）：把「过期时间是推断还是云端给的」这个事实持久化到配置条目。此前重启后 `at_expire_inferred` 会回到默认的 `false`，于是 v1.2.11 推断出来的 25 天会被传感器显示成 `token_expiry_source: cloud`，排查时容易误判成「云端说还剩 25 天」。现在同时持久化 `coolkit_at_expire_inferred` 和学到的 `coolkit_at_lifetime`，重启后诊断信息保持准确；`refresh_session` 服务的响应也补上 `at_lifetime_hours`
- v1.2.11（2026-11-01）：把「续期响应不含过期时间」时的推断值从 1 小时改为 **25 天**。CoolKit/eWeLink 官方文档明确写 *Access Token expires in 30 days, you can use Refresh Token to refresh instead of logging in again*，本账号首次认证实测也正好是 30 天 —— 说明那把 `at` 的真实寿命就是 30 天，1 小时的推断纯属过度保守，副作用是把 HA 的**停机容错窗口压到了 1 小时**：只要停机超过 1 小时，存下来的令牌就已过期，恢复后只能人工重新认证。改成 25 天（留 5 天余量）后，**停机 25 天以内恢复都能自愈，完全不需要人工**。同时新增真实寿命学习：只要云端某次真的返回了过期时间，就按那个跨度更新 `at_lifetime`，后续推断自动跟随；会话传感器新增 `at_lifetime_hours`（当前采用的寿命假设，等于容忍的停机时长）
- v1.2.10（2026-11-01）：修正续期成功后的过期时间推断。实测发现 `POST /v2/user/refresh` 成功时只返回 `at` / `rt`，**不返回过期时间**；旧代码这时会沿用上一次的过期时间（本次是 11-30），于是新令牌明明只有很短的有效期，轮询却认为「还早得很」，等到真正去续期时新令牌早就死了 —— 又变成需要重新认证。现在续期响应里没有可解析的过期时间时，一律按 1 小时推断（`rt` 续期很便宜），宁可多刷一次，也不在令牌死后才发现。同时会话传感器新增 `token_expiry_source`（`cloud` = 云端给的，`inferred` = 本地推断）和 `last_refresh_fields`（上次续期响应实际返回的字段名，用于排查网关改字段），`refresh_session` 服务的响应也一并返回这些信息，并额外给出 `token_expires_in_seconds`
- v1.2.9（2026-11-01）：新增服务 `okp_cloud.refresh_session`（手动续期云会话）。访问令牌的有效期长达数周，`rt` 续期路径要等令牌快过期才会自然触发，既没法立刻确认它真的可用，也没法在掉线时手动救一次。该服务直接调用轮询里同一套续期代码，立即用 `rt` 换新令牌、写回配置条目，并把 `refreshed_by` / `session_state` / `token_expires_at` / `error` 作为响应返回，在「开发者工具 → 操作」里就能看到结果。实测：手机 App 已登录的情况下，集成侧调用该服务仍能成功换出新的访问令牌，随后轮询、控制、回读全部正常，证明两者已互不干扰
- v1.2.8（2026-11-01）：修正访问令牌过期时间的解析与续期时机——`get-user-info` 返回的过期时间字段名不固定（`at_expire_at` / `atExpiredTime` / `expireAt`，部分为毫秒），旧代码只认一个名字，取不到时过期时间恒为 0，于是退化成「每 12 小时才刷新一次」。而续期接口要求 `Authorization` 里的访问令牌**服务端仍然认识**，刷新太晚就会在令牌已死之后才去续期，直接退化成重新认证。现在兼容多种字段名并把无过期时间时的兜底间隔改为 1 小时，确保始终在令牌还有效时完成续期
- v1.2.7（2026-11-01）：云会话传感器新增 `stale`（需要重新认证一次）状态。实测确认 `POST /v2/user/refresh` 的 `Authorization` 只接受服务端认识的访问令牌，用刷新令牌本身去带这个头会返回 `401 cannot found access token info`；因此当访问令牌已被旧版本清空或已被拒绝时，`rt` 无法自行换出新令牌，必须先重新认证一次 —— 之后 `rt` 才能接管续期。传感器之前在这种情况下仍显示 `rt`，属于误报，现已修正
- v1.2.6（2026-11-01）：**rt 续期其实一次都没成功过** —— 找到并修掉了根因。`POST /v2/user/refresh` 要求 `Authorization: Bearer <hex>` 头，缺少时服务端返回 `400 "authorization" is required`；旧代码不带这个头，且把错误只记在 debug 级别，所以每次续期都静默失败、再回退到 okplife 登录令牌（于是 App 一登录就掉线）。现在：
  ① 续期请求带上 `Authorization` 头，先试 `Bearer <访问令牌>`，再试 `Bearer <刷新令牌>` —— 即使访问令牌已过期也能续期；
  ② **不再丢弃访问令牌**：之前 401/402/403 都会把 `coolkit_at` 置空，而它正是续期请求的认证头来源，清掉就等于永久放弃自续期。现在只标记「已被拒绝」（`at_rejected`），值保留，下次轮询用 rt 换新令牌；
  ③ 仅当服务端明确拒绝刷新令牌（402/403）才丢弃 rt；400/401 属于请求格式或认证头问题，保留并继续尝试
- v1.2.5（2026-11-01）：解决「手机 App 一登录、集成就掉线」的可观测性与自愈问题——
  ① **新增诊断传感器 `sensor.*_session`（云会话）**：取值 `rt`（已存刷新令牌，自行续期，不受 App 登录影响）、`okplife`（只有访问令牌，续期必须走 OKP 登录令牌，而 App 登录会把它顶掉）、`expired`（无令牌）。属性给出令牌过期时间、最近一次续期失败原因、连续认证失败次数 —— 掉线原因一眼可见，不用再猜；
  ② **修复 `rt` 被覆盖**：`get-user-info` 若不返回 `rt`，旧代码会把已经保存的 `rt` 覆盖成 `None`，导致会话退回「依赖登录令牌」并永久失去自续期能力；现在只有拿到新值才覆盖；
  ③ **不再轻易丢弃 `rt`**：旧代码把所有 4xx 都当作「rt 被拒」并清空，连 `403 api not found`（路由/参数问题）也清，而清掉之后只能人工重新认证。现在仅 401/402（或 403 且错误信息明确指向 rt）才清空；
  ④ **日志降噪**：本地续期节流（`throttled`）不再计为认证失败，也不再输出 warning —— 之前会看到 `auth failed (5/3)` 与 `(6/3)` 交替刷屏；失败计数封顶在 3，同一错误只记一条；
  ⑤ **重新认证提示明确说明单会话限制**：提交表单会注销手机 App，反之 App 登录会顶掉集成，这是云端策略
- v1.2.4（2026-11-01）：修掉 1.2.3 的副作用——重新认证提示被冷却期拖到半小时后才出现。令牌续期失败后的冷却由 900s 降到 300s（续期请求本身已有 120s 节流），冷却期内等待的每个轮询周期也计入认证失败计数，因此连续 3 次（约 9 分钟）就会给出提示；续期一旦成功则立即清零并回到正常轮询
- v1.2.3（2026-11-01）：首次刷新失败不再让条目卡进 HA 的「重试设置」循环——令牌失效时应该弹一次重新认证，而不是持续重试把实体全部藏起来。现在首次取数失败只记一条 warning，平台照常加载，轮询继续尝试，连续 3 次认证失败后给出重新认证提示
- v1.2.2（2026-11-01）：修复「集成每几小时就掉线并要求重新认证」——
  ① **只存了 `coolkit_at` 没存 `coolkit_rt`**：CoolKit 令牌过期后唯一的续期途径是 okplife 的 `/v1/coolkit/get-user-info`，而它依赖 OKP 登录令牌，该令牌几小时就过期且 okplife 没有 refresh 接口 → 整条链路死锁，只能人工重输密码。现在改走 CoolKit 自己的 `POST /v2/user/refresh`（body `{"rt":…}`），它与 OKP 登录令牌无关，会话可无限续期；okplife 仅作兜底。同时把 `at/rt/apikey/region` 全部持久化到配置条目，HA 重启不再丢会话（升级后首次启动会自动补抓一次 `rt`）；
  ② **重启时不再因缺少 `rt` 而反复失败**：`ensure_coolkit_token()` 先试 refresh token，失败才回退 okplife；刷新节流从 300s 降到 120s，且节流不再计入认证失败；
  ③ **不再为一次抖动弹「需要重新认证」**：连续 3 个轮询周期（约 9 分钟）认证失败才会弹窗，成功一次即清零——之前 4001 出现一次就立刻建修复项，看起来像随机报错；
  ④ 轮询彻底失败时抛 `UpdateFailed`，日志里给出 `OKP auth failed (n/3)` 便于判断进展
- v1.2.1（2026-11-01）：修复 1.2.0 实测暴露的三个缺陷——① **控制全部失效**：CoolKit 写状态接口路径写错（`/v2/device/thing/update` 在网关不存在，恒返回 `403 api not found`），改为 `/v2/device/thing/status`，请求体同步改为 `{"type":1,"id":…,"params":…}`；② **重新认证流程崩溃**：`async_step_reauth` 把 HA 传入的配置条目数据当成表单输入，索引已不再保存的 `password` 抛 `KeyError`（日志表现为 `Task exception was never retrieved`），改为标准的 `reauth` + `reauth_confirm` 两步流程；③ 控制失败不再清空 CoolKit 令牌（403 属请求/权限问题，非认证问题），并向界面抛 `HomeAssistantError` 而非原始异常堆栈；重新认证改为回写完整设备列表，多设备场景不会丢设备
- v1.2.0（2026-11-01）：对照 v3.4.0 App 全量操作抓包补齐/修复——① CoolKit 令牌获取改用 App 实测的 `GET /v1/coolkit/get-user-info`（旧 `refresh-access-token` 端点 App 已不再调用，服务端可能已下线）；② 修复清扫记录接口时间戳（改为 13 位毫秒、与 App 完全一致，旧版传微秒导致地图/记录取数异常）；③ 支持账号下的多个家庭（App 可建多家庭，设备可能在任一家庭，配置时全部扫描并去重）；④ 新增 4 个传感器：移动状态（move）、版本（version）、最近清扫时间（取自清扫记录接口）、固件更新（OTA 查询，每小时探测，有新版时显示版本号）；⑤ 工作状态映射按抓包实测校准（清扫中=4）；⑥ 清扫记录开始/结束传感器改显示清扫记录编号（该字段实际是记录 ID 而非时间）；⑦ 无清扫记录时地图状态显示「暂无清扫记录」

<details>
<summary>展开</summary>

- v1.1.9（2026-10-30）：多设备与按型号能力支持——① 一个账号下的多台 OKP/乐帆扫地机全部接入（旧配置自动迁移，单设备升级即生效）；② 每台设备独立轮询与实体（电量/状态/模式/地图各一套）；③ 实体按设备实际能力创建：设备上报里没有的 dp（如地毯增压、定时任务）不再生成对应实体，避免无用/空值实体；④ 枚举语义映射表保留扩展点（当前按 K5 Ultra 校准，其他型号实测后可补充）
- v1.1.8（2026-10-30）：安全与健壮性修复——① 账号密码不再明文写入配置存储（.storage），旧条目升级后自动清理已存密码，重启/重新认证不再依赖本地密码；② 清扫地图 camera 移除无效的开/关按钮（此前 UI 会显示无法使用的开关）；③ CoolKit 令牌失效后对 OKP 云的刷新请求增加 5 分钟冷却，网络异常时不会每 3 分钟重复刷新（防风控）；④ 重新认证/重新配置表单自动预填账号
- v1.1.7（2026-10-29）：实体值全部人类可读化并支持中英双语（默认中文）——工作状态（空闲/清扫中/已暂停/回充中）、清扫模式（智能/随机/沿墙/螺旋）、地毯增压与 dp31（开启/关闭）、在线状态（在线/离线）均按 HA 官方 state 翻译机制本地化；定时任务拆为「启用的定时任务」与「定时任务总数」两个数值传感器；上次清扫开始/结束无记录时显示 —
- v1.1.6（2026-10-29）：补齐未接入的实体与功能——新增清扫模式选择器（select，智能/随机/沿墙/螺旋）、地毯增压开关（switch）、6 个诊断传感器（数据点 dp31、上次清扫开始/结束、界面活跃值、呼叫计数、定时任务摘要）
- v1.1.5（2026-10-29）：配置/重新认证时立即获取并保存长有效期 CoolKit 令牌（与手机 App 多端共存、不互顶），重启不再依赖 OKP 会话；修复自动重新认证流程在部分 HA 版本的兼容性
- v1.1.4（2026-10-29）：令牌彻底失效时自动触发 HA 重新认证流程——HA 弹出重新认证窗口，输入账号密码即可恢复（仍不会自动用密码登录，不影响手机 App）
- v1.1.3（2026-10-29）：设备状态轮询从 30 秒降为 3 分钟——OKP 云把同账号客户端视为唯一在线会话，进一步降低集成对云会话的占用，避免干扰手机 App
- v1.1.2（2026-10-29）：修复手机 App 被顶下线——OKP 云同一账号仅允许一个在线会话，集成此前 token 失效后会自动用密码重登（会把 App 会话挤掉）；现改为令牌自愈模式：全程不再调用密码登录，CoolKit 令牌过期时仅用已有 access token 静默刷新，彻底失效才提示手动重新认证（15 分钟退避）；登录只发生在首次配置/手动重新认证时
- v1.1.1（2026-10-29）：降低对 OKP 云账号的干扰，避免影响手机 App——清扫记录接口探测频率从每次轮询改为 5 分钟一次；登录失败增加 15 分钟退避（防止反复重登触发账号风控/顶掉 App 会话）
- v1.1.0（2026-10-29）：修复清扫地图 camera 实体无法注册——CoordinatorEntity.__init__ 不会链式调用 Camera.__init__，导致 Camera 基类实例属性（_webrtc_provider 等）缺失、实体添加报 AttributeError 后变为 unavailable；现显式调用 Camera.__init__，地图图片可正常在仪表盘显示
- v1.0.9（2026-10-29）：新增清扫地图功能——camera 平台提供清扫地图图片（拉取最新清扫记录地图接口并渲染为 PNG，30 分钟自动刷新）；零依赖纯 Python PNG 渲染
- v1.0.8（2026-10-29）：vacuum 实体显式暴露 battery_level 属性（新版 HA 移除 VacuumEntityFeature.BATTERY 后框架不再自动发布电量属性，前端扫地机卡片可正常显示电量）
- v1.0.7（2026-10-29）：修复 OKP 登录令牌过期（4001 请先登录）被当作普通错误、轮询卡死不重登的问题，现统一按认证错误处理并自动重登恢复
- v1.0.6（2026-10-29）：修复 CoolKit 令牌过期后轮询卡死（401 未自动重登，实体数据停更）；新增电量传感器（映射 CoolKit power 字段，%）；重登后强制刷新 CoolKit 令牌；轮询失败写日志
- v1.0.5（2026-10-26）：修复卸载时关闭 HA 托管 session 的弃用告警（2027.9 将失效）；session 生命周期完全交由 HA 管理
- v1.0.4（2026-10-25）：修复 reauth/reconfigure 误中断与 401/403 自动重登；新增诊断传感器实体（sensor 平台）；实体名称翻译全量（en / zh-Hans）
- v1.0.3（2026-10-25）：品牌图（brand/）、translations/en.json、integration_type=hub、quality_scale=bronze、session 改由 HA 托管
- v1.0.2（2026-10-25）：实体挂载到设备注册表设备（DeviceInfo）
- v1.0.1（2026-10-25）：修复 `VacuumEntityFeature.BATTERY` 在新版 HA 已移除导致的 setup 崩溃
- v1.0.0（2026-10-25）：首个云账号登录版

</details>
