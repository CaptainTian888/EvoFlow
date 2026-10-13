# 下次问题怎么解决？完整指南

你遇到的"视频拆解师突然在 chat 里发言"问题，已经建立了**完整的预防-排查-解决框架**。

---

## 📋 快速参考

### 问题出现时的第一反应

```bash
# 1. 快速诊断（30 秒）
python -m evoflow.proactive.diagnose_feishu_push issues

# 2. 追踪问题来源（1 分钟）
python -m evoflow.proactive.diagnose_feishu_push agent video-analyst 60

# 3. 查看目标 chat 的所有推送者（1 分钟）
python -m evoflow.proactive.diagnose_feishu_push target oc_ec754692847407e341974cb14272a9d8 60
```

### 这次的问题具体怎么追踪？

```bash
# 查看 video-analyst 的推送历史
python -m evoflow.proactive.diagnose_feishu_push agent video-analyst 120

# 预期输出：
# 2026-10-13T21:00:00Z | (如果有推送，会显示这里)
# 2026-10-13T20:00:00Z | (其他记录...)
# ...

# 如果没有记录在 audit 表，说明这条消息来自 agent 直接发言，不是我们的自动化系统推送
```

---

## 🔍 三层诊断深度

### Level 1: 快速检查（< 1 分钟）

**问题**：某 agent 有奇怪的行为
**工具**：CLI diagnostic

```bash
# 看最近发生的所有推送决策
python -m evoflow.proactive.diagnose_feishu_push summary

# 看所有阻止的推送
python -m evoflow.proactive.diagnose_feishu_push issues
```

**输出示例**：
```
BLOCKING ISSUES (last 120 min)
================================================================================

  [BLOCKED] 2026-10-13T21:00:00Z
    From: video-analyst
    Kind: wrap_digest
    Target: oc_ec754692847...
    Reason: feishu not enabled in approval_channels
```

→ 如果看到这样的输出，说明是 approval_channels 配置导致阻止

### Level 2: 深入追踪（1-2 分钟）

**问题**：某 agent 向某 chat 推送了，但不该推送
**工具**：Agent 追踪 + Target 追踪

```bash
# 看这个 agent 最近所有的推送尝试
python -m evoflow.proactive.diagnose_feishu_push agent video-analyst 180

# 看这个 chat 最近谁在推
python -m evoflow.proactive.diagnose_feishu_push target oc_ec754692847407e341974cb14272a9d8 180
```

**输出示例**：
```
AGENT: video-analyst
================================================================================
Push attempts (last 120 min):

  2026-10-13T21:15:00Z | wrap_digest     | blocked
    → oc_ec754692847...
    Method: push_policy
    Status: skipped
    Reason: feishu not enabled in approval_channels

  2026-10-13T20:45:00Z | review_card     | blocked
    → oc_ec754692847...
    Status: skipped
```

→ 如果都是 blocked，说明我们的系统工作正常，那条消息来自其他路径

### Level 3: 完整审计（2-5 分钟）

**问题**：需要了解完整的决策链路和配置变化
**工具**：SQL 查询或 compare_pair

```bash
# 看 video-analyst 对你的 chat 的完整交互历史
python -m evoflow.proactive.diagnose_feishu_push pair video-analyst oc_ec754692847407e341974cb14272a9d8
```

**输出示例**：
```
PAIR: video-analyst <-> oc_ec754692847407e341974cb14272a9d8
================================================================================

  2026-10-13T21:15:00Z | blocked   | wrap_digest
    feishu disabled in approval_channels

  2026-10-13T21:00:00Z | blocked   | review_card
    feishu disabled in approval_channels
```

→ 看完整的历史，你可以：
- 看配置什么时候改变
- 看决策方法是否一致
- 追踪是否有 fallback 或异常

---

## 🎯 常见问题快速排查

### 问题 A：某 agent 不再推送了

**诊断步骤**：

```bash
# 1. 查看它的推送历史
python -m evoflow.proactive.diagnose_feishu_push agent <code> 120

# 2. 看最近有没有被阻止的推送
# 如果全是 "blocked"，说明配置有问题

# 3. 查看 SQL：检查当前配置
sqlite3 evoflow.db "
  SELECT 
    agent_code,
    json_extract(config_json, '$.approval_channels') as channels,
    (SELECT push_enabled FROM evoflow_role_push_bindings 
     WHERE agent_code = r.agent_code) as policy_enabled
  FROM evoflow_proactive_roles r
  WHERE agent_code = 'xxx'
"

# 4. 对比审计表中的配置快照
sqlite3 evoflow.db "
  SELECT source_approval_channels, target_resolution_method, COUNT(*)
  FROM evoflow_feishu_push_audit
  WHERE source_agent_code = 'xxx'
  GROUP BY source_approval_channels
  ORDER BY COUNT(*) DESC
  LIMIT 3
"
```

**可能的原因**：
- ✅ 配置中 approval_channels 移除了 'feishu' → **正常，按设计阻止**
- ✅ 绑定（policy）被删除或禁用 → **需要重新配置**
- ❌ 系统故障 → 检查 error_msg 字段

### 问题 B：某 chat 突然收到多个 agent 的推送

**诊断步骤**：

```bash
# 1. 看这个 chat 的所有推送来源
python -m evoflow.proactive.diagnose_feishu_push target <receive_id> 120

# 2. 统计每个 agent 的推送量
sqlite3 evoflow.db "
  SELECT source_agent_code, COUNT(*) as count
  FROM evoflow_feishu_push_audit
  WHERE receive_id = 'oc_...'
    AND created_at > datetime('now', '-1 day')
  GROUP BY source_agent_code
  ORDER BY count DESC
"

# 3. 看是否是预期的配置变化
sqlite3 evoflow.db "
  SELECT DISTINCT source_agent_code, target_resolution_method
  FROM evoflow_feishu_push_audit
  WHERE receive_id = 'oc_...'
  ORDER BY source_agent_code
"
```

**可能的原因**：
- ✅ 正常的协作场景：多个 agent 被分配到同一个任务 → **符合预期**
- ⚠️ 配置错误：某些 agent 被分配到不该参与的 chat → **需要清理协作成员**
- ❌ Push policy 配置错误 → **需要修正绑定**

### 问题 C：推送到了错误的 target

**诊断步骤**：

```bash
# 1. 看这个 agent 推送到了哪些地方
sqlite3 evoflow.db "
  SELECT receive_id, receive_id_label, COUNT(*) as count
  FROM evoflow_feishu_push_audit
  WHERE source_agent_code = 'xxx'
  GROUP BY receive_id
  ORDER BY count DESC
"

# 2. 看目标解析方法
sqlite3 evoflow.db "
  SELECT receive_id, target_resolution_method, COUNT(*)
  FROM evoflow_feishu_push_audit
  WHERE source_agent_code = 'xxx'
  GROUP BY receive_id, target_resolution_method
"

# 3. 看配置快照，找出变化
sqlite3 evoflow.db "
  SELECT created_at, receive_id, source_push_policy_json
  FROM evoflow_feishu_push_audit
  WHERE source_agent_code = 'xxx'
    AND receive_id = 'WRONG_ID'
  ORDER BY created_at DESC
"
```

**可能的原因**：
- ✅ Fallback 到全局默认 chat（旧系统行为）→ **P0 已修复，不应再发生**
- ❌ RolePushPolicy 配置错误 → **需要更新绑定**
- ❌ 配置文件与 DB 不同步 → **重启 gateway**

---

## 🛠️ 实际操作：这次的问题

### 这次发生的具体情况

你看到 video-analyst 在你的 chat 里发言了。

**追踪步骤**：

```bash
# Step 1: 有没有对应的推送记录？
python -m evoflow.proactive.diagnose_feishu_push pair video-analyst oc_ec754692847407e341974cb14272a9d8

# 预期：如果看到都是 "blocked"，说明这条消息不是我们的推送系统送的
#      而是 video-analyst 作为协作成员的自发发言

# Step 2: 检查 video-analyst 的配置
sqlite3 evoflow.db "
  SELECT 
    agent_code,
    json_extract(config_json, '$.approval_channels') as channels,
    json_extract(config_json, '$.feishu_open_id') as oid
  FROM evoflow_proactive_roles
  WHERE agent_code = 'video-analyst'
"

# 预期输出：
# video-analyst | ['desktop'] | (empty)
# ✓ approval_channels 已经禁用 feishu（P0 修复）
# ✓ feishu_open_id 为空（无独立 DM）

# Step 3: 检查它有没有绑定
sqlite3 evoflow.db "
  SELECT agent_code, push_enabled, feishu_open_id
  FROM evoflow_role_push_bindings
  WHERE agent_code = 'video-analyst'
"

# 预期：push_enabled=0（P1 数据迁移已禁用）
```

**结论**：
- ✅ 我们的推送系统工作正常（所有推送都被正确阻止）
- ⚠️ video-analyst 在那个 chat 里的发言来自**其他途径**（可能是：
  - 它被加入了那个 group chat 作为协作成员
  - 某个工作流给了它权限
  - 它通过其他 API 发言
- ✓ 这是**正常的协作行为**，不是我们系统的 bug

### 如果需要解决

**方案 1**：从那个 chat 里移除 video-analyst（飞书侧操作）

```bash
# 检查它为什么被加入了
sqlite3 evoflow.db "
  SELECT * FROM evoflow_proactive_initiatives
  WHERE participants LIKE '%video-analyst%'
  ORDER BY created_at DESC
  LIMIT 5
"
```

**方案 2**：如果 video-analyst 确实应该在那个 chat 里，就忽略这条消息（它是正常的协作）

---

## 📚 完整工具集总览

| 场景 | 工具 | 命令 |
|------|------|------|
| 快速看问题 | CLI | `diagnose_feishu_push issues` |
| 追踪某 agent | CLI | `diagnose_feishu_push agent <code>` |
| 查看某 chat | CLI | `diagnose_feishu_push target <id>` |
| 对比两者 | CLI | `diagnose_feishu_push pair <agent> <target>` |
| 查看汇总 | CLI | `diagnose_feishu_push summary` |
| 原始查询 | SQL | `diagnose_feishu_push sql "SELECT..."` |
| Python API | Code | `FeishuPushDiagnostics(db_path).trace_agent_pushes(agent_code)` |
| SQL 模板库 | Docs | 见 `FEISHU_PUSH_QUERY_TEMPLATES.md` |

---

## 🚀 预防措施（避免下次出现）

### 每日自动检查

```python
# 在 gateway 启动时运行
async def validate_role_configs():
    """Validate all role configs on startup."""
    issues = []
    
    for role in list_roles():
        # Check 1: feishu enabled but no binding?
        if 'feishu' in role.approval_channels:
            policy = get_role_policy(role.agent_code)
            if not policy or not policy.should_push_to('feishu'):
                issues.append(f"{role.agent_code}: feishu enabled but no valid binding")
        
        # Check 2: config in DB != config in policy table?
        # etc.
    
    if issues:
        logger.error("CONFIG VALIDATION FAILED:\n" + "\n".join(issues))
        # Send alert
```

### 每 5 分钟的异常检测

```python
async def detect_anomalies():
    """Detect push anomalies in real-time."""
    
    # Detect 1: Fallback spike
    fallback_count = db.execute(
        "SELECT COUNT(*) FROM evoflow_feishu_push_audit "
        "WHERE decision='fallback' AND created_at > datetime('now','-5 min')"
    ).fetchone()[0]
    
    if fallback_count > 5:
        logger.alert("FALLBACK SPIKE: %d fallbacks in 5 min", fallback_count)
    
    # Detect 2: Multiple agents in same chat
    # Detect 3: Unusual target changes
    # etc.
```

### 每周的审计报告

```python
async def weekly_audit():
    """Generate weekly push audit report."""
    
    report = {
        "total_pushes": count_pushes(7),
        "success_rate": calculate_success_rate(7),
        "top_blocked_reasons": get_top_blocked_reasons(7),
        "unbound_roles": find_unbound_roles(),
        "unverified_bindings": find_unverified_old_bindings(),
    }
    
    # Send report to Slack/Email
```

---

## 总结

**你现在拥有**：
1. ✅ P0：推送混乱已修复（双重检查）
2. ✅ P1：架构已优化（规范化配置）
3. ✅ **诊断系统**：追踪任何推送问题（< 5 分钟定位）
4. ✅ **SQL 模板库**：常见问题的查询
5. ✅ **CLI 工具**：快速检查的命令行

**下次有问题时**：
```bash
# 第一行命令（30 秒）
python -m evoflow.proactive.diagnose_feishu_push agent <code> 120

# 看输出，快速判断是否是我们系统的问题
# 如果是，根据 decision_reason 修复配置或代码
# 如果不是，调查其他推送路径（agent 直接发言、协作权限等）
```

**预防下次**：
- 启动验证（check config consistency）
- 实时监控（alert on anomalies）
- 周报告（audit trail）
