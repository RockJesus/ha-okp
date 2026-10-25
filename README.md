# OKP Cloud 扫地机器人（用户名密码登录版）

Home Assistant 自定义集成：通过 **OKP 云账号（用户名+密码）** 接入 OKP/乐帆（Lefant）扫地机器人（如 **OKP K5 Ultra**），无需本地密钥。

## 功能

- 用户名 + 密码登录 OKP 云（`api-cn.okplife.com`），自动完成签名（sign）
- 自动发现账号下所有家庭与扫地机器人设备
- 实时状态轮询（默认 30s）：电量、清扫状态、工作状态、故障码、信号强度、固件版本
- 控制指令（通过 CoolKit 物联云）：
  - 开始清扫 / 暂停 / 停止
  - 回充（停止清扫后机器人自动回充）
  - 吸力档位：安静 / 标准 / 强力
- 已登录令牌自动缓存，CoolKit token 过期自动刷新

## 安装

1. 将 `custom_components/okp_cloud` 目录复制到 HA 的 `config/custom_components/` 下
2. 重启 Home Assistant
3. 「设置 → 设备与服务 → 添加集成」搜索 **OKP Cloud 扫地机器人**
4. 输入 OKP App 的**手机号/账号**与**密码**，提交

## 实体

| 实体 | 类型 | 说明 |
| --- | --- | --- |
| `vacuum.okp_xxx` | Vacuum | 扫地机主体（状态/电量/吸力/控制），挂载于设备注册表设备 |

状态属性包含：`work_state`、`clean_mode`（smart/random/wall_follow/spiral）、`fault_code`、`rssi`、`firmware_version`、`cleaning_area`、`cleaning_times`、`carpet_booster`、`online` 等。

## 支持设备

- OKP K5 Ultra（实测，ThingClips 白标 / CoolKit 云）
- 其他 OKP / 乐帆云账号下的扫地机理论上兼容（协议相同）

## 技术说明（协议逆向摘要）

- 登录：`POST /v5/client/login-with-password`（`password` + `account`）
- 签名：`MD5("client-id=971d3d280f96&timestamp=<毫秒>&key=okp0be4d645f610f19dc7418c7f473cc")`（从 APK `TokenInterceptor` 逆向）
- 设备：`/v2/home/list` → `/v9/home/device-list` → `/v5/home/device-detail-info`
- CoolKit：`/v1/coolkit/refresh-access-token` 换 `at`，`POST cn-apia.coolkit.cn/v2/device/thing` 查状态、`/v2/device/thing/update` 控制

## 已知限制

- 回充 = 停止清扫（CoolKit 无独立回充 dp）；若你的机型不回充，请抓包一次「回充」动作反馈后补充
- 暂停 = 停止清扫（`sweep=0`），与 App 行为一致
- 密码保存在 HA 配置存储（`.storage/`）中用于重新登录

## 版本

<details>
<summary>更新日志</summary>

- v1.0.2（2026-10-25）：实体挂载到设备注册表设备（DeviceInfo，identifiers=third_dev_id），设备下可见扫地机
- v1.0.1（2026-10-25）：修复 `VacuumEntityFeature.BATTERY` 在新版 HA 已移除导致的 vacuum 平台 setup 崩溃（登录成功但无实体）
- v1.0.0（2026-10-25）：首个云账号登录版

</details>
