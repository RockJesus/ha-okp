# OKP 会话归属验证手册（v1.5.1）

> 目的：用一个可证伪的实验，分清「HA 重启后会话失效」到底是
> **① 云端在重启时撤销了会话**，还是 **② App 登录把会话顶掉了**。
> 两者修法完全不同，所以不猜，直接测。

## 先看结论表

| 现象 | 判定 | 说明 |
|---|---|---|
| 重启后**仍正常**，`session_origin = reauth-password` | ② **没人顶号** | 上一版 v1.5.0 的问题仍在（集成侧），继续查 |
| 重启后失效，`last_rt_probe_result = renewed` | ① 云端撤销旧 token | 已被 v1.5.1 自动救回，无需手动介入 |
| 重启后失效，`last_rt_probe_result = rejected: 402/403...` | ② **会话被抢** | 厂商单会话限制，App 一登录就顶掉，属预期行为 |
| 重启后失效，`rt_issued_at` 在重启**之后**才变 | ② 会话被抢 | rt 被轮换，说明有别的客户端续过期 |
| 重启后失效，`session_origin = unknown` | 数据不足 | 老条目，需先跑一次实验 A 建立基线 |

---

## 实验 A：建立基线（不碰 App）

1. 确认 OKP App 已**完全退出**（不是切后台，是从最近任务里划掉）。
2. HA → 开发者工具 → 动作，调用 `okp_cloud.refresh_session`，参数 `force: true`。
3. 记下返回的 `session_origin`、`session_started_at`、`token_expires_in_seconds`。
   - 期望：`session_origin = reauth-password`（或 `rt-renewal`），有效期约 29 天。
4. 打开 App，随便看一眼设备页（**只读，不做任何设置**）。
5. 再调一次 `refresh_session`（`force: false`，只读）。
   - 若此时 `session_state` 仍为 `rt` → App 的只读浏览**不会**顶号。
   - 若变成 `stale` → App 每次打开都会顶号，问题定性完成，不用再做 B/C。

## 实验 B：重启对照

1. 基线正常状态下，**在 App 完全关闭的情况**下重启 HA（设置 → 系统 → 重启）。
2. 重启完成后 2 分钟内，调 `refresh_session`（`force: false`）并记录：
   `session_state` / `session_origin` / `rt_issued_at` / `last_rt_probe_result`。
3. 然后**打开 App**，再调一次，对比 `rt_issued_at` 是否被改写。
   - `rt_issued_at` 变了 = rt 被轮换 = 有别的客户端（App）在续期 → 会话被抢。
   - 没变但 `stale` = 纯云端撤销 → 集成侧问题。

## 实验 C：交叉验证（决定性）

1. 先让集成本身正常（基线 `rt`）。
2. 用手机 App 登录并把 App 留在前台，**然后**重启 HA。
3. 按顺序观察：
   - HA 日志是否出现 `the session was taken over, not lost locally`；
   - `refresh_session` 返回的 `last_rt_probe_result` 是否为 `rejected: ...`。

若 C 步骤复现失效，而 B 步骤（App 关闭）不失效 → **厂商单会话限制**，结论确定。

---

## 需要收集的三段证据

```text
1) refresh_session 返回值（重启前 / 重启后 / 打开 App 后，共 3 次）
2) HA 日志中 OKP 相关行（含 startup 的 restored 行、401、probe 结果）
3) 配置条目里的字段（.storage/core.config_entries 中 okp_cloud 条目）
   —— 重点看 coolkit_session_origin / coolkit_session_started_at / coolkit_rt_issued_at
```

## v1.5.1 已做的两件事

1. **记录来源**：每个令牌写入都带上 `coolkit_session_origin`，重启后仍能判断
   「这个会话是密码登录换来的，还是 rt 续来的」。
2. **自动探查**：遇到 `401 cannot found access token info` 时，先主动释放旧 token
   （`POST /v2/user/logout`）再用 rt 续期一次：
   - 成功 → 旧 token 只是被撤销，自动恢复，**不弹重新验证**；
   - 失败 → 记录 `the session was taken over, not lost locally`，才走重新验证。

也就是说：**如果 v1.5.1 部署后重启仍然失效，几乎可以确定是 App 顶号，而不是集成写得有问题。**
