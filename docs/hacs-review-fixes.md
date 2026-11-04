# HACS 审核意见修复记录（v1.6.7）

来源：[hacs/default#13225](https://github.com/hacs/default/pull/13225) · 由 **frenck**（HACS 维护者）于 2026-11-03T20:15:55Z 提出 `CHANGES_REQUESTED`

PR 已由机器人自动转为 **draft**，需修复后推新 release 并重新请求审核。

## 意见 1：不要暴露 CoolKit `devicekey`

> `custom_components/okp_cloud/vacuum.py` (lines 174-175) writes the CoolKit `devicekey` into the vacuum entity's state attributes (`attrs["device_key"] = ...`). On the CoolKit / eWeLink platform that key is the device's own secret (it is what eWeLink uses to encrypt LAN control). Entity attributes are visible to every Home Assistant user, end up in the recorder history and are sent to every open frontend. Please drop the `device_key` attribute; nothing in the integration needs it there.

**问题性质**：安全问题。`devicekey` 是设备自身密钥，eWeLink 用它加密局域网控制。
实体属性会：对所有 HA 用户可见 → 写入 recorder 历史 → 推送到每个打开的前端。

**修复**：删除 `attrs["device_key"]` 写入，并在原处留注释说明原因。
集成内部任何逻辑都不依赖该属性（密钥只在 API 层用于请求头）。

**验证**：v1.6.7 部署后读取实体属性，`device_key` 已不存在：

```
vacuum 状态 : idle
device_key  : 已移除 ✅
属性键      : ['battery_level', 'carpet_booster', 'clean_mode', 'cleaning_area',
               'cleaning_times', 'fan_speed', 'fan_speed_list', 'fault_code',
               'firmware_version', 'friendly_name', 'online', 'power_switch',
               'remote_move', 'rssi', 'supported_features', 'sweep_switch', 'work_state']
```

## 意见 2：地图渲染必须移出事件循环

> `custom_components/okp_cloud/coordinator.py` (lines 559-563) calls `parse_map_paths` and `render_map_png` directly from the async `_async_refresh_map`. `render_map_png` (`map_render.py`, lines 41-89) loops over every grid cell and every output byte in Python and then runs `zlib.compress` over the whole RGB buffer, all on the event loop, which stalls every other integration while a map renders. Please move it to the executor, for example `self.map_image = await self.hass.async_add_executor_job(render_map_png, points)`.

**问题性质**：性能/可用性。`render_map_png` 是纯同步 CPU 函数——逐格遍历 + 整块 RGB 缓冲 `zlib.compress`，
在事件循环里执行会阻塞**所有**其他集成。

**修复**：两步都放进 executor（`parse_map_paths` 同样是纯 CPU 遍历）：

```python
points = await self.hass.async_add_executor_job(parse_map_paths, paths)
if not points:
    self.map_error = "map data empty"
    return
self.map_image = await self.hass.async_add_executor_job(render_map_png, points)
```

**验证**：v1.6.7 部署后检查 HA 系统日志，无 okp_cloud 相关的
`Detected blocking call ... inside the event loop` 告警
（唯一一条来自 `netease_lyrics`，与本集成无关）。
地图 camera 实体 `camera.ke_ting_okp_k5_ultra_cleaning_map` 正常工作。

## 部署结果

| 项 | 状态 |
|---|---|
| 集成版本 | v1.6.7 |
| 会话 | `rt`，realtime `connected`，有效期 28.5 天 |
| 协调器 | 1 |
| 实体数 | 34 |
| 错误 | 无 |
| 机器人状态 | `idle`（正常可控制） |

## 待办：PR 侧操作（需仓库所有者执行）

代码与 release 已就绪，但以下两步**必须在 GitHub 网页上手动完成**——
当前 token 是 fine-grained 且只授权了 `RockJesus/ha-okp`，
对 `hacs/default` 无写权限（GraphQL 返回 `FORBIDDEN: Resource not accessible by personal access token`）。

1. 在 [PR #13225](https://github.com/hacs/default/pull/13225) 页面点击 **「Ready for review」**
   （PR 当前为 draft 状态，不转为 ready 就不会重新进入审核队列）；
2. 如有需要，在 PR 下回复一条简短说明，指出 v1.6.7 已按意见修复。

> 注意 HACS 的规则：审核期间**不要**反复评论 PR、不要新开 PR、不要请求 review。
> 转 ready 后静候维护者处理即可。
