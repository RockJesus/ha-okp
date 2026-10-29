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
- 📡 30s 状态轮询：电量、清扫状态、工作状态、故障码、信号强度、固件版本、清扫面积/次数
- 🎮 完整控制：开始清扫 / 暂停 / 停止 / 回充 / 三档吸力（安静 · 标准 · 强力）
- 🔄 CoolKit 令牌过期自动刷新、登录失效自动重登
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
| `sensor.okp_cloud_*_work_state` | 传感器 | 工作状态（清扫/回充/暂停/待机） |
| `sensor.okp_cloud_*_clean_mode` | 传感器 | 清扫模式（smart/random/wall_follow/spiral） |
| `sensor.okp_cloud_*_rssi` | 传感器 | 信号强度（dBm，诊断） |
| `sensor.okp_cloud_*_fault_code` | 传感器 | 故障码（诊断） |
| `sensor.okp_cloud_*_firmware_version` | 传感器 | 固件版本（诊断） |
| `sensor.okp_cloud_*_cleaning_area` | 传感器 | 清扫面积 |
| `sensor.okp_cloud_*_cleaning_times` | 传感器 | 清扫次数 |
| `sensor.okp_cloud_*_carpet_booster` | 传感器 | 地毯增压（诊断） |
| `sensor.okp_cloud_*_online` | 传感器 | 在线状态（诊断） |

> 扫地机实体还附带扩展属性：`work_state`、`clean_mode`、`fault_code`、`rssi`、`firmware_version`、`cleaning_area`、`cleaning_times`、`carpet_booster`、`online`、`last_error`。

## 🎛️ 支持设备

- **OKP K5 Ultra**（实测，CoolKit / ThingClips 云）
- 其他 OKP / 乐帆云账号下的扫地机理论上兼容（协议相同）

## 🔧 技术说明（协议逆向摘要）

<details>
<summary>点击展开</summary>

- 登录：`POST /v5/client/login-with-password`（`password` + `account`）
- 签名：`MD5(client-id=...&timestamp=<ms>&key=...)`——自 APK `TokenInterceptor` 指令级逆向，43/43 个抓包请求复算命中
- 设备：`/v2/home/list` → `/v9/home/device-list` → `/v5/home/device-detail-info`
- 状态：`/v1/coolkit/refresh-access-token` 换取 CoolKit `at` → `POST cn-apia.coolkit.cn/v2/device/thing`
- 控制：`POST cn-apia.coolkit.cn/v2/device/thing/update`

</details>

## ⚠️ 已知限制

- **回充 = 停止清扫**（CoolKit 无独立回充 dp）；若你的机型不回充，请抓包一次「回充」动作反馈后补充
- **暂停 = 停止清扫**（`sweep=0`），与 App 行为一致
- 密码保存在 HA 配置存储（`.storage/`）中，用于重新登录与自动重登

## 📝 更新日志

<details>
<summary>展开</summary>

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
