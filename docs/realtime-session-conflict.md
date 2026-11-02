# 实时推送导致会话失效 — 根因分析（v1.5.3）

## 线索

> v1.3.3 引入实时推送之前，集成功能正常；引入之后，会话开始不稳。

这条线索直接指向**实时 socket**，而不是令牌持久化。复盘代码后确认：v1.5.0~v1.5.2 一直在查"令牌有没有存对"，
方向错了——令牌存得是对的，问题是**有人在不停把它换掉**。

## 机制

CoolKit 的 `userOnline` 是**单会话登记**：

- 一个账号同一时刻只允许一个在线客户端；
- 握手时提交的 `at` 就是"当前会话"；
- 新的 `userOnline` 会让前一个 `at` 失效。

而 `ensure_coolkit_token()` 的续期规则是：token 年龄超过 1 小时 → 续期。**每次续期都会轮换 `at`。**

两者叠加就形成了闭环：

```
socket 握手 (AT-1 登记)
      ↓
轮询续期 → AT-2        （socket 手里的 AT-1 成了旧会话）
      ↓
socket 检测到 token 变了 → 重连 → userOnline(AT-2)
      ↓
轮询 401              （AT-2 刚续出来就被自己顶掉）
      ↓
再续期 → AT-3 → socket 再重连 ……
```

循环几轮后，云端把整个会话一起销毁，本地 `at`/`rt` 全部成为孤儿。
这就是实测到的 **"rt 也被拒"**——不是 rt 本身有问题，而是它所属的会话已经不存在了。

## 时间线印证

| 版本 | 行为 | 结果 |
|---|---|---|
| v1.3.3 之前 | 只有轮询，续期是唯一写者 | 稳定 |
| v1.3.3 之后 | socket + 轮询两个写者抢同一个 slot | 逐步恶化，最终 `401 cannot found access token info` |
| v1.5.0~v1.5.2 | 一直在修"令牌持久化" | 无效（方向错） |
| **v1.5.3** | **引入会话归属标记，禁止并发续期** | **待验证** |

## v1.5.3 的修复

### 1. 会话归属（`api.session_socket_at`）

socket 握手成功后登记"我在用这个 at"；断连时**按值比较**后释放
（避免旧 socket 把新 socket 的归属清掉）。

### 2. 续期闸门

`ensure_coolkit_token()` 开头：

```python
if self.session_socket_at and self.coolkit_at == self.session_socket_at:
    return   # socket 持有会话，不续期
```

所有续期入口（轮询、控制指令、服务调用）都汇聚到这个函数，一处闸门全覆盖。

### 3. socket 重连不再无条件续期

原代码每次 `_async_session()` 都调 `ensure_coolkit_token()`，这是自伤点：重连自己触发续期，续期又让重连失败。

### 4. 到期前主动交还

token 剩余 15 分钟时，socket 主动断开并交还会话（`WS_HANDOVER_SECONDS`），
轮询续期后等待 5 分钟（`WS_HANDOVER_RETRY`）再重连，让"续期"和"登记"错开。

### 5. 手动续期不再打断会话

`refresh_session` 的 `force: true` 在 socket 在线时直接返回提示，不强行轮换。

### 6. 心跳失败不再静默

原来 `_async_ping` 遇到异常直接 `return`，socket 变哑却看起来健康。现在记日志。

## 仿真验证

```
A) 旧逻辑（无闸门），token 已 2 小时：
   poll#1: RENEWED  at=AT-2
   poll#2: RENEWED  at=AT-3
   poll#3: RENEWED  at=AT-4     ← 每轮询一次轮换一次

B) v1.5.3（socket 持有会话）：
   poll#1: skipped (socket owns session)
   poll#2: skipped (socket owns session)
   poll#3: skipped (socket owns session)   ← 续期次数 0

C) socket 交还会话后：
   RENEWED at=AT-5                          ← 恢复正常续期
```

## 验证方法（部署后）

1. 重新验证一次，拿到干净会话
2. 观察 `refresh_session` 返回的 `session_held_by_socket`：
   - `true` → socket 持有会话，此时**不应该**出现任何续期
   - 连续多天观察 `session_state` 是否保持 `rt`
3. 关键指标：**`token_age_seconds` 应持续增长**。
   如果它反复归零，说明续期仍在频繁发生，闸门没生效。
4. 重启 HA 后应自动恢复（无 `401`），若仍失效再看 `last_rt_probe_result`

## 仍存在的限制

厂商**单会话**是硬约束：集成与手机 App 依然不能同时在线。
v1.5.3 解决的是**集成内部**（socket 与轮询）互抢，不改变 App 登录会顶掉集成这一事实。
