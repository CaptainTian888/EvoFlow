# EvoFlow Proactive Push 架构缺陷分析

## 现象
- **问题1**：空工作汇报（零任务完成）也会推送给你
- **问题2**：所有员工汇报推到同一个 chat（你的视频拆解对话）
- **问题3**：员工没有独立的推送通道绑定

## 根本原因

### 1. **数据结构设计缺陷**

#### 当前模型
```python
# evoflow_proactive_roles 表
agent_code (PRIMARY KEY)
role_name
config_json  {
  "feishu_open_id": "",  # 空！无绑定
  "approval_channels": ["desktop", "feishu"],
  "push_target_id": "",  # 空！无绑定
  # ... 其他配置
}

# evoflow_channels_push_log 表
kind: "wrap_digest"
channel: "feishu"
chat_id: NULL  # 推送目标不清晰
thread_id: NULL
payload_json: {...}
```

**问题**：
- `feishu_open_id` 和 `push_target_id` 都**默认为空**
- 没有表记录 `role ↔ chat_id` 的映射
- 没有表记录 `role ↔ open_id` 的映射

#### 设计失陷
1. **缺少人员-通道映射表**
   - 应该有 `evoflow_role_channels` 表：`(agent_code, channel, target_id, target_type)`
   - 现在只在 `config_json` 嵌套字段里，难以查询和更新

2. **推送目标解析链路混乱**
   ```
   resolve_role_feishu_target(role)
     ├─ 检查 role.config.feishu_open_id  (通常为空)
     ├─ 调用 resolve_push_target(push_target_id=agent_code)
     │  ├─ 如果 push_target_id 为空
     │  └─ 返回全局默认 chat  ← BUG！所有 role 都 fallback 这里
     └─ 返回 None
   ```
   **每次都同一个 fallback chat**，导致混淆

3. **"approval_channels" 和 "push_channel" 的语义分裂**
   - `approval_channels`: ["desktop", "feishu"] 控制**是否推送**
   - 但**推送到哪里**由 `resolve_push_target` 决定
   - 两套逻辑解耦，导致无法按 role 精准路由

### 2. **业务逻辑缺陷**

#### 问题A：缺乏有效性检验
```python
async def push_wrap_digest_card(role, report):
    if not _role_wants_feishu(role):
        return None  # 检查 approval_channels 包含 "feishu"
    
    # ... 计算 think_summary, counts ...
    
    target = resolve_role_feishu_target(role)
    if not target:
        # ✅ 这里会 skip
        return None
    
    # 但问题是：target 99% 会返回全局 default_chat
    # 因为所有 role 的 feishu_open_id / push_target_id 都空！
```

**后果**：
- 缺少有效绑定的 role，会推送到**错误的 chat**
- 而不是 skip

#### 问题B：缺乏空工作的过滤
```python
if not created and not pending and not completed and not failed and not executing:
    return None  # 这道过滤在我之前的改动里加了
    # 但原代码是：
    # if ... and not think_summary and not has_named_item:
    #     return None
    # 所以有文字说明（"本轮没待办"）就放行了
```

**后果**：空工作也会推，形成骚扰

### 3. **表设计缺陷**

现在的表结构：
```sql
-- evoflow_proactive_roles
CREATE TABLE evoflow_proactive_roles (
    agent_code TEXT PRIMARY KEY,
    config_json TEXT,  -- 嵌套字段，难以查询
    ...
);

-- evoflow_channels_push_log (日志，不是配置)
CREATE TABLE evoflow_channel_push_log (
    channel TEXT,
    chat_id TEXT,       -- 这次推送的目标
    thread_id TEXT,
    ...
);
```

**应该有**（缺失的规范化）：
```sql
-- 新表：人员-推送通道绑定
CREATE TABLE evoflow_role_push_bindings (
    agent_code TEXT PRIMARY KEY,
    feishu_open_id TEXT,        -- DM open_id
    feishu_chat_id TEXT,        -- 或专属 group chat_id
    feishu_channel_type TEXT,   -- 'open_id' | 'chat_id' | 'user_id'
    push_enabled BOOLEAN,       -- 全局开关
    push_enabled_at TEXT,
    PRIMARY KEY (agent_code)
);

-- 改进：config_json 只存业务逻辑，推送目标分离
-- evoflow_proactive_roles.config_json 不包含 feishu_open_id / push_target_id
```

---

## 系统性问题总结

| 层级 | 问题 | 影响 | 根因 |
|------|------|------|------|
| **数据** | 人员无独立推送绑定 | 所有 role fallback 同一 chat | 缺少规范化表 |
| **数据** | 推送目标在 config_json 嵌套 | 难以查询、更新、一致性检验 | 没有 single-fact 表 |
| **逻辑** | approval_channels 和 push routing 解耦 | 无法按 role 精准控制流向 | 设计时没有统一的 policy 概念 |
| **逻辑** | 缺乏 fallback 的有效性检验 | 推到错误的 chat 而不是 skip | 对"绑定失败"的处理不明确 |
| **过滤** | 空工作判断链路不清 | 骚扰推送（已修复） | marker 列表不完整 + `think_summary` 误判 |

---

## 修复方案（从根本上解决）

### Phase 1: 数据结构重组（迁移）

1. **创建新表 `evoflow_role_push_bindings`**
   ```sql
   CREATE TABLE evoflow_role_push_bindings (
       agent_code TEXT PRIMARY KEY,
       -- Feishu 绑定（三选一）
       feishu_open_id TEXT,        -- DM（最优：每人独立）
       feishu_chat_id TEXT,        -- group chat（备选）
       feishu_user_id TEXT,        -- 或其他标识
       feishu_target_type TEXT,    -- 'open_id' | 'chat_id' | 'user_id'
       
       -- 通用推送控制
       push_enabled BOOLEAN DEFAULT 1,
       push_channels TEXT,         -- 'feishu,wecom,slack' (逗号分隔)
       
       -- WeChat / Slack 等其他渠道的绑定（扩展）
       wecom_bot_id TEXT,
       slack_channel_id TEXT,
       
       -- 元数据
       last_verified_at TEXT,      -- 绑定有效性最后验证时间
       created_at TEXT NOT NULL,
       updated_at TEXT NOT NULL
   );
   ```

2. **从 config_json 迁移数据**
   ```python
   # 脚本：extract config_json.feishu_open_id → role_push_bindings.feishu_open_id
   # 同时设置 feishu_target_type = 'open_id'
   ```

3. **简化 config_json**
   - 从 config 中移除 `feishu_open_id`, `feishu_app_id`, `feishu_app_secret`, `feishu_bound_at`
   - 这些字段全部归到 `role_push_bindings` 表

### Phase 2: 业务逻辑清理

1. **统一的 push policy 对象**
   ```python
   @dataclass
   class RolePushPolicy:
       """Single source of truth for role's push configuration."""
       agent_code: str
       push_enabled: bool  # 全局开关
       channels: dict[str, ChannelPushConfig]  # {"feishu": {...}}
       
       def should_push_to(self, channel: str) -> bool:
           """Check if this role should receive pushes on this channel."""
           return self.push_enabled and channel in self.channels
       
       def resolve_target(self, channel: str) -> tuple[str, str] | None:
           """Return (target_id, target_type) or None if not configured."""
           cfg = self.channels.get(channel)
           if not cfg or not cfg.enabled:
               return None
           return cfg.target_id, cfg.target_type
   
   @dataclass
   class ChannelPushConfig:
       enabled: bool
       target_id: str      # open_id / chat_id / 邮箱等
       target_type: str    # 'open_id' | 'chat_id' | 'user_id' | 'email'
       verified_at: str | None  # 绑定是否有效
   ```

2. **新的推送目标解析逻辑**
   ```python
   def resolve_role_push_target(role: Role, channel: str) -> tuple[str, str] | None:
       """
       Resolve push target for role on given channel.
       
       Returns:
           (target_id, target_type) if configured and verified
           None if:
               - role has push_enabled=False
               - channel not in role.push_channels
               - no valid binding exists
               (never fallback to global default!)
       """
       # 1. 从 role_push_bindings 查询
       policy = RolePushPolicy.from_db(role.agent_code)
       if not policy:
           logger.warning("no push policy found for %s", role.agent_code)
           return None
       
       # 2. 检查是否应该推送
       if not policy.should_push_to(channel):
           logger.debug("push disabled for %s on %s", role.agent_code, channel)
           return None
       
       # 3. 解析目标
       target = policy.resolve_target(channel)
       if not target:
           logger.warning(
               "no valid %s target for %s (binding may be invalid)",
               channel, role.agent_code
           )
           return None
       
       return target
   ```

3. **改进空工作判断**
   ```python
   def is_meaningful_patrol_report(report: dict) -> bool:
       """
       Check if this patrol round produced meaningful output.
       
       Returns False if:
           - All counters are zero (no tasks completed/pending/failed)
           - Summary text indicates idle patrol (no actual work)
           - No meaningful items in report
       """
       counts = report.get("counts", {})
       has_work = any([
           int(counts.get("completed", 0)),
           int(counts.get("pending_approval", 0)),
           int(counts.get("failed", 0)),
           int(counts.get("executing", 0)),
           len(report.get("created_task_ids", [])),
       ])
       
       if not has_work:
           return False  # No task output
       
       # 即使有 think_summary，如果计数都是 0，也不推
       # (think_summary 只作为补充说明，不决定是否推送)
       return True
   ```

### Phase 3: 数据验证和监控

1. **绑定有效性检验**
   ```python
   async def verify_role_push_binding(agent_code: str, channel: str) -> bool:
       """
       Test if this role's push binding is actually working.
       
       For Feishu: send a test message to the open_id/chat_id
       and mark verified_at timestamp if successful.
       """
       policy = RolePushPolicy.from_db(agent_code)
       target = policy.resolve_target(channel)
       if not target:
           return False
       
       target_id, target_type = target
       try:
           # Send test message
           await feishu_send_test_message(target_id, target_type)
           # Mark verified
           db.role_push_bindings.update_verified_at(agent_code, channel)
           return True
       except Exception as e:
           logger.warning("binding verification failed: %s", e)
           return False
   ```

2. **监控：推送路由日志**
   ```python
   # 每次推送都明确记录
   logger.info(
       "push %s to %s: role=%s target=%s policy=%s",
       kind,      # wrap_digest, review_card, ...
       channel,   # feishu
       agent_code,
       target_id,
       policy.to_dict()  # 当时的策略快照
   )
   ```

---

## 立即行动项（优先级）

### 🔴 P0（立即）
- ✅ 修复空工作过滤（已做）
- ✅ 修复 resolve_role_feishu_target 按 agent_code 路由（已做）
- **新增**：给各 role 配置 `feishu_open_id` 或建立 role ↔ chat 映射

### 🟡 P1（本周）
- 创建 `evoflow_role_push_bindings` 表
- 从 config_json 迁移数据
- 实现新的 `resolve_role_push_target` 函数
- 添加绑定有效性检验（test message）

### 🟢 P2（后续）
- 前端 UI：各 role 的推送配置管理界面
- 监控面板：推送路由日志和失败率
- 支持多渠道（WeChat、Slack）

---

## 为什么会频发这类问题？

### 根本原因分析

1. **业务逻辑分散**
   - 推送目标的定义在 3 个地方：`config_json`, `approval_channels`, `resolve_push_target`
   - 没有单一真实源（single source of truth）

2. **缺乏类型约束**
   - `feishu_open_id` 在 config 中是字符串，可以为空
   - 推送时没有强制验证是否真实有效
   - Python 的 `getattr(..., "") or ""` 让空值无声地传播

3. **测试不足**
   - 没有单元测试验证 "没有绑定的 role 不推送"
   - 没有端到端测试验证 "role A 推到 chat A，role B 推到 chat B"

4. **设计阶段缺陷**
   - 最初设计时假设"推送目标总是存在"（"维度坍塌"）
   - 后来加功能时没有重构数据结构，只是打补丁
   - `config_json` 成了垃圾堆

### 如何避免重复

1. **数据设计原则**
   - 一个概念 = 一张表（第一范式）
   - 推送目标配置不要嵌套在 config_json 里

2. **代码设计原则**
   - 写一个 `Policy` 或 `Config` 对象，集中所有逻辑
   - 避免分散在多个函数里的 getattr 链

3. **测试先行**
   - 对每个 role，验证推送目标的完整性
   - 参数化测试：role 无绑定 → 不推送

4. **监控告警**
   - 推送失败时，立即打 warn 日志，可视化监控
   - 定期（每天）检验所有 role 的绑定有效性
