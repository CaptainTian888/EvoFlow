# Feishu 推送诊断 — SQL 查询模板

## 快速查询

### 1. 查看最近的所有推送决策

```sql
SELECT 
    created_at, push_kind, source_agent_code, 
    decision, receive_id_label, decision_reason
FROM evoflow_feishu_push_audit
ORDER BY created_at DESC 
LIMIT 20;
```

**用途**：快速了解最近发生了什么推送

---

### 2. 查找某 agent 的所有推送

```sql
SELECT 
    created_at, push_kind, decision, 
    receive_id, receive_id_label,
    target_resolution_method, status, error_msg
FROM evoflow_feishu_push_audit
WHERE source_agent_code = 'video-analyst'
ORDER BY created_at DESC;
```

**用途**：追踪某个 agent 的完整推送历史

---

### 3. 查找推送到某个 chat 的所有 agent

```sql
SELECT 
    created_at, source_agent_code, source_role_name,
    push_kind, decision, decision_reason
FROM evoflow_feishu_push_audit
WHERE receive_id = 'oc_ec754692847407e341974cb14272a9d8'
ORDER BY created_at DESC;
```

**用途**：看哪些 agent 在向你的 chat 推送

**示例输出**：
```
created_at             | source_agent_code        | decision  | reason
2026-10-13T21:00:00Z   | video-analyst            | blocked   | feishu disabled in approval_channels
2026-10-13T20:30:00Z   | douyin-analyst           | allowed   | resolved via push_policy
```

---

### 4. 找出所有被阻止的推送

```sql
SELECT 
    created_at, source_agent_code, push_kind,
    receive_id_label, decision_reason, status
FROM evoflow_feishu_push_audit
WHERE decision = 'blocked' OR status = 'failed'
ORDER BY created_at DESC;
```

**用途**：诊断为什么某些推送没有送出

---

### 5. 检查 fallback（兜底）滥用

```sql
SELECT 
    source_agent_code, COUNT(*) as fallback_count,
    GROUP_CONCAT(DISTINCT push_kind) as kinds
FROM evoflow_feishu_push_audit
WHERE decision = 'fallback'
GROUP BY source_agent_code
ORDER BY fallback_count DESC;
```

**用途**：发现是否有 agent 频繁使用 fallback（说明配置不完整）

---

### 6. 比较某 agent 对某 target 的完整历史

```sql
SELECT 
    created_at, push_kind, decision,
    source_approval_channels, target_resolution_method,
    decision_reason, error_msg
FROM evoflow_feishu_push_audit
WHERE source_agent_code = 'video-analyst'
  AND receive_id = 'oc_ec754692847407e341974cb14272a9d8'
ORDER BY created_at DESC;
```

**用途**：深入理解某对 (agent, target) 的交互

---

### 7. 按决策原因分组统计

```sql
SELECT 
    decision, decision_reason, COUNT(*) as count,
    COUNT(DISTINCT source_agent_code) as unique_agents,
    COUNT(DISTINCT receive_id) as unique_targets
FROM evoflow_feishu_push_audit
WHERE created_at > datetime('now', '-24 hours')
GROUP BY decision, decision_reason
ORDER BY count DESC;
```

**用途**：了解最常见的推送问题

---

### 8. 检查配置一致性 — 启用 feishu 但无绑定的 agent

```sql
SELECT 
    r.agent_code, r.role_name,
    json_extract(r.config_json, '$.approval_channels') as approval_channels,
    json_extract(r.config_json, '$.feishu_open_id') as legacy_oid,
    COALESCE(b.push_enabled, 0) as policy_enabled,
    b.feishu_open_id as policy_oid
FROM evoflow_proactive_roles r
LEFT JOIN evoflow_role_push_bindings b ON r.agent_code = b.agent_code
WHERE json_extract(r.config_json, '$.approval_channels') LIKE '%feishu%'
  AND r.agent_code NOT IN (
    SELECT DISTINCT source_agent_code 
    FROM evoflow_feishu_push_audit 
    WHERE decision = 'allowed'
  )
ORDER BY r.agent_code;
```

**用途**：找出配置不一致的 agent（可能导致推送失败）

---

### 9. 按小时统计推送活动

```sql
SELECT 
    strftime('%Y-%m-%d %H:00', created_at) as hour,
    COUNT(*) as total_attempts,
    SUM(CASE WHEN decision = 'allowed' THEN 1 ELSE 0 END) as allowed,
    SUM(CASE WHEN decision = 'blocked' THEN 1 ELSE 0 END) as blocked,
    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
FROM evoflow_feishu_push_audit
WHERE created_at > datetime('now', '-24 hours')
GROUP BY hour
ORDER BY hour DESC;
```

**用途**：看推送活动的时间分布

---

### 10. 找出从未成功推送的 agent

```sql
SELECT 
    source_agent_code,
    COUNT(*) as total_attempts,
    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_count,
    MAX(created_at) as last_attempt
FROM evoflow_feishu_push_audit
WHERE decision != 'blocked'  -- 排除主动阻止的
GROUP BY source_agent_code
HAVING failed_count > 0 AND failed_count = total_attempts
ORDER BY total_attempts DESC;
```

**用途**：发现系统中有问题的 agent

---

## 组合诊断模式

### 问题场景 1：某 chat 有多个 agent 在推送

```sql
-- 1. 看有多少 agent
SELECT COUNT(DISTINCT source_agent_code) as agent_count
FROM evoflow_feishu_push_audit
WHERE receive_id = 'oc_...' 
  AND decision = 'allowed'
  AND created_at > datetime('now', '-24 hours');

-- 2. 具体是哪些 agent
SELECT DISTINCT source_agent_code, source_role_name
FROM evoflow_feishu_push_audit
WHERE receive_id = 'oc_...'
  AND decision = 'allowed'
  AND created_at > datetime('now', '-24 hours');

-- 3. 看他们的目标配置
SELECT 
    source_agent_code, 
    COUNT(*) as push_count,
    COUNT(DISTINCT push_kind) as push_types,
    MAX(created_at) as latest_push
FROM evoflow_feishu_push_audit
WHERE receive_id = 'oc_...'
  AND decision = 'allowed'
GROUP BY source_agent_code
ORDER BY latest_push DESC;
```

### 问题场景 2：某 agent 的推送突然失败

```sql
-- 1. 看最近 10 次推送的状态
SELECT 
    created_at, push_kind, decision, status, 
    error_msg, target_resolution_method
FROM evoflow_feishu_push_audit
WHERE source_agent_code = 'xxx'
ORDER BY created_at DESC LIMIT 10;

-- 2. 看配置是否改变
SELECT 
    created_at, 
    source_approval_channels,
    source_push_policy_json,
    decision_reason
FROM evoflow_feishu_push_audit
WHERE source_agent_code = 'xxx'
ORDER BY created_at DESC LIMIT 5;

-- 3. 检查数据库中的当前配置
SELECT 
    r.agent_code,
    json_extract(r.config_json, '$.approval_channels') as approval_channels,
    b.push_enabled, b.feishu_open_id
FROM evoflow_proactive_roles r
LEFT JOIN evoflow_role_push_bindings b ON r.agent_code = b.agent_code
WHERE r.agent_code = 'xxx';
```

### 问题场景 3：推送路由到了错误的 target

```sql
-- 1. 看这个 agent 的目标分布
SELECT 
    receive_id, receive_id_label,
    COUNT(*) as push_count,
    SUM(CASE WHEN decision = 'allowed' THEN 1 ELSE 0 END) as allowed,
    MAX(created_at) as latest
FROM evoflow_feishu_push_audit
WHERE source_agent_code = 'xxx'
GROUP BY receive_id
ORDER BY latest DESC;

-- 2. 看目标解析方法是否一致
SELECT 
    receive_id,
    target_resolution_method,
    COUNT(*) as count
FROM evoflow_feishu_push_audit
WHERE source_agent_code = 'xxx'
  AND decision = 'allowed'
GROUP BY receive_id, target_resolution_method;

-- 3. 如果有多个 target，查看每个的配置快照
SELECT 
    receive_id,
    source_approval_channels,
    source_push_policy_json,
    COUNT(*) as times_used
FROM evoflow_feishu_push_audit
WHERE source_agent_code = 'xxx'
GROUP BY receive_id
ORDER BY times_used DESC;
```

---

## 视图快速查询

```sql
-- 查看最近的所有问题
SELECT * FROM v_recent_push_issues LIMIT 20;

-- 统计问题类型
SELECT 
    decision, decision_reason, COUNT(*) as count
FROM v_recent_push_issues
GROUP BY decision, decision_reason
ORDER BY count DESC;
```

---

## 性能提示

- 所有查询都有索引支持，应该 < 100ms
- 使用 `created_at > datetime('now', '-X hours')` 限制时间范围
- 对于历史数据可以考虑归档
