# OKP 会话归属验证 — 实测结果（v1.5.2）

> 2026-11-02 实测，HA 实例（地址略），集成 v1.5.2。
> 结论先行：**不是集成写坏了会话，是云端把会话一起撤销了（刷新令牌也被拒）。**

## 实测时间线

| 时间 | 版本 | 操作 | `session_state` | `last_rt_probe_result` | 关键日志 |
|---|---|---|---|---|---|
| 19:48 | v1.5.0 | 只读查询 | `stale` | — | `401: cannot found access token info` |
| 19:49 | — | 重启 HA | — | — | — |
| 19:55 | v1.5.1 | 重启后查询 | `stale` / `session_origin=unknown` | — | `CK_ENDPOINT_USER_LOGOUT is not defined`（v1.5.1 自身 Bug） |
| 20:01 | v1.5.2 | 重启后查询 | `stale` | **`rejected: 401 cannot found access token info`** | `the session was taken over, not lost locally` |
| 20:01 | v1.5.2 | `force: true` 强制续期 | 仍 `stale` | 同上 | 续期确实被云端拒绝，不是本地判断错 |

## 关键证据

1. **`has_refresh_token = true`** — rt 确实存在于配置条目里，没有被写丢。
2. **`last_rt_probe_result = rejected`** — 拿这个 rt 去续期，云端回 `401 cannot found access token info`。
3. **`rt_rejected_at` / `rt_reject_count` 仍为 0** — 说明云端回的是 401 而不是 402/403：
   云端不是"这个刷新令牌不合法"，而是"**整个会话已经不存在了**"。

三条合起来只有一个解释：**会话在服务端被销毁**，本地的 at 和 rt 都变成了孤儿凭据。
（注：原生 App 与集成共用同一个 CoolKit 会话、且该云"新登录顶掉旧会话"，
所以唯一能造成"会话整体消失"的外部事件就是**别处登录了同一个账号**。）

## 已排除的可能

- ❌ 不是 rt 没存下来：`has_refresh_token = true`
- ❌ 不是本版本写入字段不全：v1.5.0 起所有写入都走 `persisted_token_fields()`
- ❌ 不是云端临时抖动：重启前后两次、加上 `force: true`，三次结果一致
- ❌ 不是本机重启导致：重启前后都是 `stale`，重启并没有让状态变差

## 影响与恢复

- 34 个实体仍存在，但电量 / 工作状态 / 云会话全部为 `unknown` / `stale`
- **恢复只能靠一次重新验证**（输入密码）：设置 → 设备与服务 → OKP → 重新验证
- 代价：密码登录会挤掉 App 当前登录（厂商单会话限制，无法避免）

## 长期规避建议

既然厂商限制"同一时刻只保留一个会话"，集成与 App **不可能真正并存**。可行做法：

1. **只用集成**（推荐）：App 只在偶尔看地图时打开，看完后回 HA 重新验证一次；
2. **只用 App**：把 HA 集成删掉，避免每天互相踢；
3. **等待厂商支持多端**：CoolKit 部分账号支持多客户端 token，当前账号看起来不支持。

## v1.5.2 之后的自动行为

遇到同样情况时，集成会：

1. 先主动 `POST /v2/user/logout` 释放旧 token；
2. 用 rt 续期一次；
3. 续成功 → 自动恢复，**不弹重新验证**；
4. 续失败 → 日志明确写 `the session was taken over, not lost locally`，
   诊断的 `last_rt_probe_result` 直接给出 `rejected: ...`，然后才走重新验证。

也就是说，下一次再出问题，一眼就能从诊断里看出是"被顶号"还是"集成的问题"。
