# 智能体 Feishu 推送问题诊断系统

## 问题分类

### Type A: 自动化推送混乱（已解决）
- 值班汇报（wrap_digest）
- 任务卡片（review_card, running_work）
- 协作收口（tree_receipt）
- **症状**：推送到错误的 chat 或被错误的 agent 拦截
- **根因**：配置分散、绑定缺失、默认值滥用

### Type B: Agent 协作权限问题（当前）
- Agent 作为成员加入 chat，自由发言
- **症状**：某 agent 在不该它参与的 chat 里出现
- **根因**：协作权限管理不清、成员关系未审计

---

## 完整诊断系统

### 层 1：实时监控（Channel Diagnostic）

**新增表**：`evoflow_feishu_push_audit`

```sql
CREATE TABLE IF NOT EXISTS evoflow_feishu_push_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- 推送来源
    push_kind TEXT NOT NULL,           -- 'wrap_digest' | 'review_card' | 'self_intro' | 'agent_reply' | 'collab_tree' | etc.
    triggered_by TEXT NOT NULL,        -- 'system' | 'agent' | 'user'
    trigger_event TEXT,                -- 任务完成 | 协作开始 | 手动请求 | etc.
    
    -- 源角色
    source_agent_code TEXT NOT NULL,   -- 谁发起的
    source_role_name TEXT,             -- 角色名字
    
    -- 目标
    receive_id TEXT NOT NULL,          -- chat_id / open_id
    receive_id_type TEXT NOT NULL,     -- 'chat_id' | 'open_id' | 'user_id'
    receive_id_label TEXT,             -- 目标描述（chat 名、人名）
    
    -- 推送决策
    decision TEXT NOT NULL,            -- 'allowed' | 'blocked' | 'fallback'
    decision_reason TEXT,              -- 阻止原因或选择理由
    
    -- 配置信息快照
    source_approval_channels TEXT,     -- approval_channels 当时值
    source_push_policy_json TEXT,      -- RolePushPolicy 当时快照
    target_resolution_method TEXT,     -- 'legacy_config' | 'push_policy' | 'default_fallback'
    
    -- 结果
    status TEXT NOT NULL,              -- 'success' | 'failed' | 'skipped'
    error_msg TEXT,
    feishu_message_id TEXT,
    
    -- 元数据
    request_id TEXT,                   -- trace ID
    gateway_pid INTEGER,
    created_at TEXT NOT NULL,
    INDEX idx_source (source_agent_code, created_at DESC),
    INDEX idx_target (receive_id, created_at DESC),
    INDEX idx_decision (decision, created_at DESC)
);
```

### 层 2：查询和诊断工具

**诊断脚本 `diagnose_feishu_push.py`**

```python
import sqlite3
from datetime import datetime, timedelta
from typing import Any

class FeishuPushDiagnostics:
    """Diagnose Feishu push issues."""
    
    def __init__(self, db_path: str):
        self.db = sqlite3.connect(db_path)
        self.db.row_factory = sqlite3.Row
    
    def audit_recent_pushes(self, minutes: int = 60) -> dict[str, Any]:
        """Get recent push decisions."""
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        cur = self.db.execute("""
            SELECT 
                push_kind, decision, COUNT(*) as count,
                GROUP_CONCAT(DISTINCT source_agent_code) as agents
            FROM evoflow_feishu_push_audit
            WHERE created_at > ?
            GROUP BY push_kind, decision
            ORDER BY created_at DESC
        """, (cutoff.isoformat(),))
        
        result = {
            "period": f"last {minutes} minutes",
            "cutoff": cutoff.isoformat(),
            "summary": []
        }
        
        for row in cur.fetchall():
            result["summary"].append({
                "kind": row["push_kind"],
                "decision": row["decision"],
                "count": row["count"],
                "agents": row["agents"].split(","),
            })
        
        return result
    
    def trace_agent_pushes(self, agent_code: str, minutes: int = 60) -> list[dict]:
        """Trace all pushes from a specific agent."""
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        cur = self.db.execute("""
            SELECT 
                created_at, push_kind, decision, decision_reason,
                receive_id, receive_id_label, receive_id_type,
                source_push_policy_json, target_resolution_method,
                status, error_msg, feishu_message_id
            FROM evoflow_feishu_push_audit
            WHERE source_agent_code = ? AND created_at > ?
            ORDER BY created_at DESC
        """, (agent_code, cutoff.isoformat()))
        
        result = []
        for row in cur.fetchall():
            result.append(dict(row))
        
        return result
    
    def trace_target_receives(self, receive_id: str, minutes: int = 120) -> list[dict]:
        """Trace all pushes to a specific chat/dm."""
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        cur = self.db.execute("""
            SELECT 
                created_at, push_kind, decision, source_agent_code, source_role_name,
                decision_reason, source_approval_channels,
                source_push_policy_json, target_resolution_method,
                status, error_msg
            FROM evoflow_feishu_push_audit
            WHERE receive_id = ? AND created_at > ?
            ORDER BY created_at DESC
        """, (receive_id, cutoff.isoformat()))
        
        result = []
        for row in cur.fetchall():
            result.append(dict(row))
        
        return result
    
    def find_blocking_issues(self, minutes: int = 120) -> list[dict]:
        """Find all blocked pushes and their reasons."""
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        cur = self.db.execute("""
            SELECT 
                created_at, push_kind, source_agent_code,
                receive_id, receive_id_label, decision_reason, error_msg
            FROM evoflow_feishu_push_audit
            WHERE (decision = 'blocked' OR status = 'failed') AND created_at > ?
            ORDER BY created_at DESC
        """, (cutoff.isoformat(),))
        
        result = []
        for row in cur.fetchall():
            result.append(dict(row))
        
        return result
    
    def compare_decisions(self, agent_code: str, receive_id: str) -> dict[str, Any]:
        """Compare consecutive decisions for a role-target pair."""
        cur = self.db.execute("""
            SELECT 
                created_at, push_kind, decision, decision_reason,
                source_approval_channels, source_push_policy_json,
                target_resolution_method, status, error_msg
            FROM evoflow_feishu_push_audit
            WHERE source_agent_code = ? AND receive_id = ?
            ORDER BY created_at DESC LIMIT 10
        """, (agent_code, receive_id))
        
        rows = [dict(row) for row in cur.fetchall()]
        return {
            "agent": agent_code,
            "target": receive_id,
            "history": rows,
        }
    
    def print_report(self, agent_code: str = None, receive_id: str = None):
        """Print diagnostic report."""
        print("\n=== FEISHU PUSH DIAGNOSTICS ===\n")
        
        if agent_code:
            print(f"AGENT: {agent_code}")
            print("-" * 60)
            trace = self.trace_agent_pushes(agent_code)
            for entry in trace[:10]:
                print(f"  {entry['created_at']} | {entry['push_kind']:15s} | {entry['decision']:10s} | {entry['receive_id_label']or entry['receive_id']}")
                if entry['decision_reason']:
                    print(f"    Reason: {entry['decision_reason']}")
                if entry['error_msg']:
                    print(f"    Error: {entry['error_msg']}")
                print()
        
        if receive_id:
            print(f"\nTARGET: {receive_id}")
            print("-" * 60)
            trace = self.trace_target_receives(receive_id)
            for entry in trace[:10]:
                print(f"  {entry['created_at']} | {entry['source_agent_code']:20s} | {entry['decision']:10s} | {entry['push_kind']}")
                if entry['decision_reason']:
                    print(f"    Reason: {entry['decision_reason']}")
                print()
        
        if not agent_code and not receive_id:
            print("Recent push decisions:")
            summary = self.audit_recent_pushes(60)
            for item in summary["summary"]:
                print(f"  {item['kind']:15s} | {item['decision']:10s} x{item['count']}")
            
            print("\nBlocked/Failed pushes:")
            blocked = self.find_blocking_issues(60)
            for entry in blocked[:5]:
                print(f"  {entry['created_at']} | {entry['source_agent_code']:20s} | {entry['decision_reason']}")
```

### 层 3：改进推送逻辑（收集审计信息）

**改进 `feishu_notify.py` 的 logging**

```python
import logging
import json
from datetime import datetime

# 创建审计日志器
audit_logger = logging.getLogger("feishu_push_audit")

async def log_push_decision(
    *,
    push_kind: str,
    source_agent_code: str,
    source_role_name: str = "",
    receive_id: str = "",
    receive_id_type: str = "chat_id",
    receive_id_label: str = "",
    decision: str,  # 'allowed' | 'blocked' | 'fallback'
    decision_reason: str = "",
    source_approval_channels: list = None,
    source_push_policy = None,
    target_resolution_method: str = "",
    status: str = "pending",
    error_msg: str = "",
    feishu_message_id: str = "",
    request_id: str = "",
) -> None:
    """Log push decision to audit table and structured logs."""
    
    from evoflow.runtime.ports import get_app_db
    
    db = get_app_db()
    if db is None:
        return
    
    # 转换 policy 为 JSON 快照
    policy_json = ""
    if source_push_policy:
        try:
            policy_json = json.dumps(source_push_policy.to_dict() if hasattr(source_push_policy, 'to_dict') else source_push_policy)
        except:
            pass
    
    # 插入审计记录
    cur = db.cursor()
    try:
        cur.execute("""
            INSERT INTO evoflow_feishu_push_audit (
                push_kind, triggered_by, trigger_event,
                source_agent_code, source_role_name,
                receive_id, receive_id_type, receive_id_label,
                decision, decision_reason,
                source_approval_channels, source_push_policy_json,
                target_resolution_method,
                status, error_msg, feishu_message_id,
                request_id, gateway_pid, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            push_kind, "system", "",
            source_agent_code, source_role_name,
            receive_id, receive_id_type, receive_id_label,
            decision, decision_reason,
            json.dumps(source_approval_channels or []),
            policy_json,
            target_resolution_method,
            status, error_msg, feishu_message_id,
            request_id, os.getpid(), datetime.utcnow().isoformat() + "Z"
        ))
        db.commit()
    except Exception as e:
        logger.warning("Failed to log push decision: %s", e, exc_info=True)
    
    # 同时输出结构化日志
    audit_logger.info(
        "push_decision",
        extra={
            "push_kind": push_kind,
            "source_agent": source_agent_code,
            "receive_id": receive_id,
            "decision": decision,
            "reason": decision_reason,
            "method": target_resolution_method,
            "status": status,
        }
    )
```

**改进 `resolve_role_feishu_target`**

```python
async def resolve_role_feishu_target_with_audit(
    role: Any,
    request_id: str = ""
) -> tuple[str, str, dict] | None:
    """Resolve target with full audit trail."""
    
    from .push_binding_repo import RolePushBindingRepository
    from .push_policy import RolePushPolicy
    
    agent_code = str(getattr(role, "agent_code", "") or "").strip()
    role_name = str(getattr(role, "role_name", "") or "").strip()
    approval_channels = list(getattr(getattr(role, "config", None), "approval_channels", None) or [])
    
    audit_trail = {
        "agent_code": agent_code,
        "role_name": role_name,
        "approval_channels": approval_channels,
        "methods_tried": [],
        "final_decision": None,
    }
    
    # Method 1: Legacy config
    cfg = getattr(role, "config", None)
    open_id = str(getattr(cfg, "feishu_open_id", "") or "").strip()
    
    if open_id:
        audit_trail["methods_tried"].append({
            "method": "legacy_config.feishu_open_id",
            "found": True,
            "target_id": open_id,
            "target_type": "open_id",
        })
        audit_trail["final_decision"] = "allowed_via_legacy"
        
        await log_push_decision(
            push_kind="target_resolution",
            source_agent_code=agent_code,
            source_role_name=role_name,
            receive_id=open_id,
            receive_id_type="open_id",
            decision="allowed",
            decision_reason="Found in legacy config.feishu_open_id",
            source_approval_channels=approval_channels,
            target_resolution_method="legacy_config",
            request_id=request_id,
        )
        
        return open_id, "open_id", audit_trail
    
    # Method 2: RolePushPolicy
    policy = None
    if agent_code:
        try:
            policy = RolePushBindingRepository.get_policy(agent_code)
        except Exception as e:
            logger.debug("Failed to load RolePushPolicy for %s: %s", agent_code, e)
        
        if policy and policy.should_push_to("feishu"):
            target = policy.resolve_target("feishu")
            if target:
                target_id, target_type = target
                audit_trail["methods_tried"].append({
                    "method": "push_policy",
                    "found": True,
                    "target_id": target_id,
                    "target_type": target_type,
                    "verified_at": policy.channels["feishu"].verified_at if "feishu" in policy.channels else None,
                })
                audit_trail["final_decision"] = "allowed_via_policy"
                
                await log_push_decision(
                    push_kind="target_resolution",
                    source_agent_code=agent_code,
                    source_role_name=role_name,
                    receive_id=target_id,
                    receive_id_type=target_type,
                    decision="allowed",
                    decision_reason=f"Found in RolePushPolicy ({target_type})",
                    source_approval_channels=approval_channels,
                    source_push_policy=policy,
                    target_resolution_method="push_policy",
                    request_id=request_id,
                )
                
                return target_id, target_type, audit_trail
        else:
            audit_trail["methods_tried"].append({
                "method": "push_policy",
                "found": False,
                "reason": "policy not found" if not policy else "feishu not enabled in policy",
            })
    
    # No valid binding
    audit_trail["final_decision"] = "blocked"
    audit_trail["block_reason"] = "No valid binding found (legacy or policy)"
    
    await log_push_decision(
        push_kind="target_resolution",
        source_agent_code=agent_code,
        source_role_name=role_name,
        receive_id="",
        receive_id_type="",
        decision="blocked",
        decision_reason="No valid feishu binding (neither legacy config nor push policy)",
        source_approval_channels=approval_channels,
        source_push_policy=policy,
        target_resolution_method="none",
        request_id=request_id,
    )
    
    return None
```

---

## 排查工具集

### 工具 1：快速诊断脚本

```bash
# 查看最近 1 小时的推送决策
python -c "
from evoflow.proactive.diagnostics import FeishuPushDiagnostics
d = FeishuPushDiagnostics('evoflow.db')
d.print_report()
"

# 查看某 agent 的推送历史
python -c "
from evoflow.proactive.diagnostics import FeishuPushDiagnostics
d = FeishuPushDiagnostics('evoflow.db')
d.print_report(agent_code='video-analyst')
"

# 查看某 chat 的所有推送
python -c "
from evoflow.proactive.diagnostics import FeishuPushDiagnostics
d = FeishuPushDiagnostics('evoflow.db')
d.print_report(receive_id='oc_ec754692847407e341974cb14272a9d8')
"
```

### 工具 2：SQL 查询模板

```sql
-- 问题 1：某 role 最近的所有推送决策
SELECT 
    created_at, push_kind, decision, receive_id_label,
    decision_reason, status, error_msg
FROM evoflow_feishu_push_audit
WHERE source_agent_code = 'video-analyst'
ORDER BY created_at DESC LIMIT 20;

-- 问题 2：某 chat 的所有推送来源
SELECT 
    created_at, source_agent_code, source_role_name,
    push_kind, decision, decision_reason
FROM evoflow_feishu_push_audit
WHERE receive_id = 'oc_ec754692847407e341974cb14272a9d8'
ORDER BY created_at DESC;

-- 问题 3：所有被拦截的推送
SELECT 
    created_at, source_agent_code, push_kind,
    receive_id, decision_reason, error_msg
FROM evoflow_feishu_push_audit
WHERE decision = 'blocked' OR status = 'failed'
ORDER BY created_at DESC LIMIT 20;

-- 问题 4：某 agent 的推送策略变化历史
SELECT 
    created_at, push_kind, source_approval_channels,
    source_push_policy_json, target_resolution_method, decision
FROM evoflow_feishu_push_audit
WHERE source_agent_code = 'video-analyst'
ORDER BY created_at DESC;

-- 问题 5：检查 fallback 滥用
SELECT 
    COUNT(*) as count, source_agent_code,
    decision_reason
FROM evoflow_feishu_push_audit
WHERE decision = 'fallback'
GROUP BY source_agent_code
ORDER BY count DESC;
```

### 工具 3：监控告警

```python
# 监控脚本：检测异常推送
class PushAnomalyDetector:
    """Detect anomalous push patterns."""
    
    @staticmethod
    def check_fallback_spike(db, window_minutes: int = 30, threshold: int = 5):
        """Alert if fallback decisions spike."""
        cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
        cur = db.execute("""
            SELECT COUNT(*) as count FROM evoflow_feishu_push_audit
            WHERE decision = 'fallback' AND created_at > ?
        """, (cutoff.isoformat(),))
        
        count = cur.fetchone()[0]
        if count > threshold:
            logger.error(
                "ALERT: Fallback push spike detected! %d fallbacks in %d min",
                count, window_minutes
            )
            return True
        return False
    
    @staticmethod
    def check_same_target_multiple_agents(db, receive_id: str, window_minutes: int = 60):
        """Alert if multiple agents suddenly push to same target."""
        cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
        cur = db.execute("""
            SELECT COUNT(DISTINCT source_agent_code) as agent_count
            FROM evoflow_feishu_push_audit
            WHERE receive_id = ? AND decision = 'allowed' AND created_at > ?
        """, (receive_id, cutoff.isoformat()))
        
        count = cur.fetchone()[0]
        if count > 3:  # 超过 3 个 agent 推到同一个 target
            logger.warning(
                "ALERT: Multiple agents (%d) pushing to %s in %d min",
                count, receive_id, window_minutes
            )
            return True
        return False
```

---

## 完整流程：预防 → 排查 → 解决

### 预防（Prevention）

1. **配置验证（startup）**
   ```python
   def validate_all_role_configs():
       """On startup, check all roles have valid configs."""
       issues = []
       for role in ProactiveRepository.list_roles():
           if 'feishu' in role.config.approval_channels:
               # Check: should have either legacy open_id or policy binding
               policy = RolePushBindingRepository.get_policy(role.agent_code)
               legacy_oid = role.config.feishu_open_id
               if not legacy_oid and not (policy and policy.should_push_to("feishu")):
                   issues.append(f"{role.agent_code}: feishu enabled but no valid binding!")
       
       if issues:
           logger.error("CONFIG VALIDATION FAILED:\n" + "\n".join(issues))
   ```

2. **每日审计（daily job）**
   ```python
   async def daily_push_config_audit():
       """Daily audit of push configurations."""
       db = get_app_db()
       
       # 1. Check for roles with approval_channels='feishu' but no binding
       cur = db.execute("""
           SELECT r.agent_code FROM evoflow_proactive_roles r
           WHERE json_extract(r.config_json, '$.approval_channels') LIKE '%feishu%'
           EXCEPT
           SELECT agent_code FROM evoflow_role_push_bindings
           WHERE push_enabled = 1 AND (feishu_open_id <> '' OR feishu_chat_id <> '')
       """)
       
       unbound = [row[0] for row in cur.fetchall()]
       if unbound:
           logger.warning("Unbound roles with feishu enabled: %s", unbound)
       
       # 2. Check for unverified bindings older than 7 days
       cur = db.execute("""
           SELECT agent_code FROM evoflow_role_push_bindings
           WHERE feishu_open_id <> '' AND feishu_verified_at IS NULL
           AND created_at < datetime('now', '-7 days')
       """)
       
       unverified = [row[0] for row in cur.fetchall()]
       if unverified:
           logger.warning("Unverified bindings (>7 days): %s", unverified)
   ```

### 排查（Investigation）

**遇到问题时的排查步骤**：

```python
async def investigate_push_issue(
    symptom: str,  # 'mixed_chat' | 'no_push' | 'wrong_target' | etc.
    agent_code: str = "",
    receive_id: str = "",
):
    """Interactive investigation of push issues."""
    
    from .diagnostics import FeishuPushDiagnostics
    d = FeishuPushDiagnostics(get_app_db())
    
    if symptom == 'mixed_chat':
        # Multiple agents in same chat?
        if not receive_id:
            return "Need receive_id"
        
        print(f"Agents pushing to {receive_id} in last 2 hours:")
        trace = d.trace_target_receives(receive_id, minutes=120)
        agents = {}
        for entry in trace:
            ag = entry['source_agent_code']
            agents.setdefault(ag, []).append(entry['decision'])
        
        for ag, decisions in sorted(agents.items()):
            print(f"  {ag}: {decisions}")
    
    elif symptom == 'no_push':
        # Role not pushing when expected?
        if not agent_code:
            return "Need agent_code"
        
        print(f"Push history for {agent_code} (last 2 hours):")
        trace = d.trace_agent_pushes(agent_code, minutes=120)
        if not trace:
            print("  NO PUSHES RECORDED")
        else:
            for entry in trace:
                print(f"  {entry['created_at']}: {entry['decision']} ({entry['decision_reason']})")
    
    elif symptom == 'wrong_target':
        # Pushing to wrong place?
        if not agent_code or not receive_id:
            return "Need both agent_code and receive_id"
        
        print(f"Comparing {agent_code} <-> {receive_id}:")
        result = d.compare_decisions(agent_code, receive_id)
        for entry in result['history']:
            print(f"  {entry['created_at']}: {entry['decision']}")
            print(f"    Method: {entry['target_resolution_method']}")
            print(f"    Reason: {entry['decision_reason']}")
```

### 解决（Resolution）

根据诊断结果自动修复：

```python
async def auto_remediate_push_issue(issue_type: str, agent_code: str):
    """Automatic remediation of common issues."""
    
    if issue_type == 'unbound_role_with_feishu_enabled':
        # 症状：role 启用了 feishu 但无绑定
        # 方案：禁用 feishu
        logger.warning("Auto-disabling feishu for unbound role: %s", agent_code)
        
        role = ProactiveRepository.get_role(agent_code)
        if role:
            cfg = role.config
            if 'feishu' in cfg.approval_channels:
                cfg.approval_channels = [c for c in cfg.approval_channels if c != 'feishu']
                ProactiveRepository.update_role(role)
    
    elif issue_type == 'unverified_binding_too_old':
        # 症状：绑定超过 7 天未验证
        # 方案：尝试验证或标记为失败
        logger.warning("Attempting verification for old binding: %s", agent_code)
        
        try:
            from app.channels.service import get_channel_service
            service = get_channel_service()
            
            # Send test message
            policy = RolePushBindingRepository.get_policy(agent_code)
            if policy and policy.should_push_to("feishu"):
                target = policy.resolve_target("feishu")
                if target:
                    target_id, target_type = target
                    await service.feishu_push_markdown(
                        target_id,
                        "[System] Binding verification test",
                        receive_id_type=target_type
                    )
                    RolePushBindingRepository.mark_verified(agent_code, "feishu")
                    logger.info("Verified binding for %s", agent_code)
        except Exception as e:
            logger.error("Verification failed for %s: %s", agent_code, e)
            # Mark binding as broken?
            
    elif issue_type == 'multiple_agents_same_chat':
        # 症状：多个 agent 被加入了同一个 chat（协作场景）
        # 方案：审计，但不自动干预（这可能是正常的）
        logger.info("Multiple agents in same chat (likely collaborative): %s", agent_code)
```

---

## 集成到项目中

### Step 1：添加审计表

```bash
# 修改 schema.py，添加 evoflow_feishu_push_audit 表
# 运行迁移
python migrate_push_audit.py
```

### Step 2：启用审计日志

```python
# 在 feishu_notify.py 的每个推送函数中调用 log_push_decision()
# 在 resolve_role_feishu_target() 中添加 audit_trail 返回值
```

### Step 3：启用监控

```python
# 在 gateway startup 时
validate_all_role_configs()

# 每天定时
schedule_job(daily_push_config_audit, "0 2 * * *")
schedule_job(PushAnomalyDetector.check_fallback_spike, "*/5 * * * *")
```

### Step 4：暴露诊断 API

```python
@router.get("/api/v1/diagnostics/push/{agent_code}")
async def diagnose_push(agent_code: str):
    """Public diagnostic endpoint."""
    from evoflow.proactive.diagnostics import FeishuPushDiagnostics
    d = FeishuPushDiagnostics(get_app_db())
    return {"trace": d.trace_agent_pushes(agent_code)}

@router.get("/api/v1/diagnostics/push-audit")
async def audit_summary():
    """Get audit summary."""
    from evoflow.proactive.diagnostics import FeishuPushDiagnostics
    d = FeishuPushDiagnostics(get_app_db())
    return d.audit_recent_pushes(60)
```

---

## 总结：完整的诊断框架

| 环节 | 工具 | 覆盖内容 |
|------|------|--------|
| **预防** | 启动验证 + 日审计 | 配置一致性、绑定完整性 |
| **检测** | 异常检测 | 推送模式变化、fallback 滥用 |
| **排查** | 审计表查询 + 诊断脚本 | 推送决策链路、配置快照 |
| **修复** | 自动修复 + API | 禁用异常推送、验证过期绑定 |
| **可视化** | 诊断 API + 前端面板 | 实时推送路由图 |

这样，**任何推送问题都能 1 分钟定位、追踪、解决**。
