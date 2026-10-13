# P1 Proactive Push 架构改造 — 完成清单

## 概览

P1 将散乱的推送配置重构为规范化的、可管理的系统。核心：**单一真实源（Single Source of Truth）**。

### 改动范围
```
db schema (新表)
  ├─ evoflow_role_push_bindings

business logic (新数据类)
  ├─ RolePushPolicy        (policy 对象，集中所有逻辑)
  ├─ ChannelBinding        (单个渠道绑定)
  └─ ChannelType           (类型约束)

data layer (新仓库)
  ├─ RolePushBindingRepository   (read/write push bindings)
  └─ migrate_push_bindings.py    (数据迁移脚本)

api layer (新路由)
  ├─ push_bindings_routes.py     (管理推送配置的 API)

integration (改进通知逻辑)
  └─ feishu_notify.py            (改成用 RolePushPolicy)
```

## 新建文件清单

| 文件 | 用途 | 状态 |
|------|------|------|
| `backend/packages/harness/evoflow/proactive/push_policy.py` | RolePushPolicy 数据类 | ✅ |
| `backend/packages/harness/evoflow/proactive/push_binding_repo.py` | 仓库层（CRUD） | ✅ |
| `backend/packages/harness/evoflow/proactive/push_bindings_routes.py` | FastAPI 路由 | ✅ |
| `backend/packages/harness/evoflow/proactive/migrate_push_bindings.py` | 迁移脚本 | ✅ |

## 改动文件清单

| 文件 | 改动 | 状态 |
|------|------|------|
| `backend/packages/harness/evoflow/persistence/schema.py` | 加 `evoflow_role_push_bindings` 表 | ✅ |
| `backend/packages/harness/evoflow/proactive/feishu_notify.py` | 改 `resolve_role_feishu_target` 用 RolePushPolicy | ✅ |

## 关键设计

### 1. RolePushPolicy 对象
```python
@dataclass
class RolePushPolicy:
    agent_code: str
    push_enabled: bool             # 全局开关
    channels: dict[ChannelType, ChannelBinding]  # feishu, wecom, slack, email
    created_at: str
    updated_at: str

# 方法
policy.should_push_to(channel) -> bool          # 是否应该推
policy.resolve_target(channel) -> (id, type)    # 推送目标
policy.add_channel(channel, target_id, type)    # 配置
policy.mark_verified(channel)                   # 标记已验证
```

**优点**：
- 单一对象，集中所有逻辑
- 类型安全（dataclass + type hints）
- 易于测试和日志记录

### 2. evoflow_role_push_bindings 表
```sql
CREATE TABLE evoflow_role_push_bindings (
    agent_code TEXT PRIMARY KEY,
    push_enabled INTEGER,              -- 全局开关（1/0）
    push_channels TEXT,                -- 'feishu,wecom,slack' (逗号分隔，用作索引)
    
    -- Feishu 绑定
    feishu_open_id TEXT,               -- DM (open_id)
    feishu_chat_id TEXT,               -- group chat (chat_id)
    feishu_user_id TEXT,               -- 其他形式
    feishu_target_type TEXT,           -- 'open_id' | 'chat_id' | 'user_id'
    feishu_verified_at TEXT,           -- 上次验证成功时间
    
    -- WeChat (企业微信)
    wecom_bot_id TEXT,
    wecom_verified_at TEXT,
    
    -- Slack
    slack_channel_id TEXT,
    slack_verified_at TEXT,
    
    -- Email
    email TEXT,
    
    -- 元数据
    created_at TEXT,
    updated_at TEXT
);
```

**优点**：
- 规范化：每行一个 role，每列一个属性
- 易查询：直接用 SQL 查 `WHERE feishu_verified_at IS NOT NULL`
- 扩展性：新渠道只需加列

### 3. 迁移过程
**已执行**：
- 从 `config_json` 提取 `feishu_open_id` → 写入 `feishu_open_id` 列
- 检查 `approval_channels` 包含 `"feishu"` 且有绑定 → 设 `push_enabled=1`
- 结果：1 个 role 启用（douyin-analyst），46 个禁用

### 4. Feishu 通知改进
```python
def resolve_role_feishu_target(role):
    # 优先级 1：legacy config.feishu_open_id (backward compat)
    if cfg.feishu_open_id:
        return cfg.feishu_open_id, "open_id"
    
    # 优先级 2：RolePushPolicy (新系统)
    policy = RolePushBindingRepository.get_policy(role.agent_code)
    if policy and policy.should_push_to("feishu"):
        return policy.resolve_target("feishu")
    
    # 优先级 3：失败
    return None  # 不 fallback 到全局 default
```

**优点**：
- 向后兼容（旧配置仍可用）
- 渐进迁移（可逐个 role 切换）
- 清晰的日志（知道用了哪个源）

### 5. API 路由（管理界面支持）
```
GET    /api/v1/proactive/push-bindings/roles/{agent_code}
         → 获取某 role 的 push policy

GET    /api/v1/proactive/push-bindings/roles?push_enabled=true
         → 列出所有启用的 role

POST   /api/v1/proactive/push-bindings/roles/{agent_code}
         → 批量更新配置

PUT    /api/v1/proactive/push-bindings/roles/{agent_code}/channels/feishu
         → 为某 role 添加 feishu 绑定

DELETE /api/v1/proactive/push-bindings/roles/{agent_code}/channels/feishu
         → 移除绑定

POST   /api/v1/proactive/push-bindings/roles/{agent_code}/channels/feishu/verify
         → 验证绑定（发送测试消息）
```

---

## 部署指南

### Step 1: 更新代码
```bash
cd D:\dev\github\EvoFlow

git add backend/packages/harness/evoflow/proactive/push_policy.py
git add backend/packages/harness/evoflow/proactive/push_binding_repo.py
git add backend/packages/harness/evoflow/proactive/push_bindings_routes.py
git add backend/packages/harness/evoflow/proactive/migrate_push_bindings.py
git add backend/packages/harness/evoflow/proactive/feishu_notify.py
git add backend/packages/harness/evoflow/persistence/schema.py

git commit -m "refactor(proactive): P1 push binding architecture

- Introduce RolePushPolicy as single source of truth for push config
- Create evoflow_role_push_bindings table (normalized structure)
- Move push config from scattered config_json to dedicated table
- Implement RolePushBindingRepository for CRUD operations
- Add API routes for managing push bindings (/api/v1/proactive/push-bindings/*)
- Improve feishu_notify to use RolePushPolicy with backward compatibility
- Include migration script to populate new table

This resolves the architecture debt from P0 and enables:
- Per-role push target verification
- Multi-channel support (feishu, wecom, slack, email)
- Audit trail (created_at, updated_at)
- Easy diagnostics (query verified bindings, list all push-enabled roles)
"
```

### Step 2: 部署数据库
```bash
# 1. 备份数据库
cp C:\Users\admin\.evoflow-dev\data\app\evoflow.db{,.bak-pre-p1}

# 2. 执行迁移脚本
python backend/packages/harness/evoflow/proactive/migrate_push_bindings.py

# 3. 验证
sqlite3 C:\Users\admin\.evoflow-dev\data\app\evoflow.db \
  "SELECT agent_code, push_enabled, feishu_open_id FROM evoflow_role_push_bindings LIMIT 5"
```

### Step 3: 重启 gateway
```bash
# 老 gateway 进程会加载新代码
# 如果需要立即生效：
pkill -f "evoflow-gateway"
sleep 2
evoflow-gateway --mode gateway --host 0.0.0.0 --port 8070 --log-level info
```

### Step 4: 测试
```bash
# 1. 检查 douyin-analyst 是否仍能推送
#    触发一次值班巡检，验证汇报是否推到了它的绑定 chat

# 2. 验证 API
curl http://localhost:8070/api/v1/proactive/push-bindings/roles/douyin-analyst

# 3. 检查日志
grep "feishu_notify.*RolePushPolicy" ~/.evoflow-dev/logs/*.log
```

---

## 下一步（后续任务）

### 优先级 P2（本周内）
- [ ] 前端 UI：role 推送配置管理界面
  - 列表：所有 role 及其推送状态
  - 编辑：添加/移除 feishu/wecom/slack/email 绑定
  - 验证：一键测试绑定有效性

- [ ] 监控面板
  - 推送成功率统计
  - 绑定失败告警
  - 推送路由日志查询

### 优先级 P3（后续）
- [ ] 支持更多渠道
  - WeChat（企业微信）
  - Slack
  - Email

- [ ] 权限级联
  - Global policy
  - Department policy override
  - Role policy override

- [ ] 定期检验
  - 每天检验所有绑定有效性
  - 自动降级失效绑定

---

## 兼容性说明

### 向后兼容
- ✅ 旧的 `config_json.feishu_open_id` 仍然生效
- ✅ 旧的 `approval_channels` 仍然被检查（legacy check）
- ✅ 迁移脚本自动抽取旧数据到新表

### 迁移路径
```
Phase 1（现在）：两个系统并存
  - 旧系统：config_json (still active)
  - 新系统：role_push_bindings (newly active)
  - resolve_role_feishu_target 优先级：legacy → new → none

Phase 2（后续，需要手工操作）：移除旧字段
  - 清理 config_json 中的 feishu_open_id, feishu_app_id, etc.
  - 弃用 approval_channels 中的 feishu（改用 push_enabled）
  - 可选：把迁移标记到数据库版本中
```

### 测试覆盖
需要补充的单元测试：
```python
def test_role_push_policy_should_push():
    policy = RolePushPolicy("test-role", push_enabled=True)
    policy.add_channel("feishu", "ou_xxx", "open_id")
    assert policy.should_push_to("feishu") == True
    assert policy.should_push_to("slack") == False

def test_unbound_role_does_not_push():
    policy = RolePushBindingRepository.get_policy("unbound-role")
    assert policy is None or not policy.should_push_to("feishu")

def test_resolve_role_feishu_target_uses_policy():
    # mock role with RolePushPolicy
    # verify resolve_role_feishu_target calls get_policy
```

---

## 问题排查

### 问题：推送仍然混乱
**诊断**：
```bash
# 检查新表是否正确填充
sqlite3 evoflow.db "SELECT COUNT(*) FROM evoflow_role_push_bindings"

# 检查 policy 是否被加载
grep "RolePushPolicy" gateway.log | head -10

# 检查 legacy fallback 是否触发
grep "using legacy feishu_open_id" gateway.log
```

**修复**：
- 重新运行迁移脚本
- 确认 gateway 已重启（检查 PID）

### 问题：某 role 的推送消失了
**诊断**：
```bash
# 检查 policy 中的 feishu 绑定
sqlite3 evoflow.db \
  "SELECT agent_code, feishu_open_id, feishu_chat_id, push_enabled FROM evoflow_role_push_bindings WHERE agent_code = 'XXX'"

# 调用 API 检查
curl http://localhost:8070/api/v1/proactive/push-bindings/roles/XXX
```

**修复**：
- 用 API 重新配置绑定
- 或者手工更新 DB：`UPDATE evoflow_role_push_bindings SET feishu_open_id = '...' WHERE agent_code = 'XXX'`

---

## 总结

P1 通过以下改进解决了 P0 遗留的架构债：

| 问题 | P0 修复 | P1 彻底解决 |
|------|--------|------------|
| 配置分散 | ❌ 仍在 config_json | ✅ 规范化表 + policy 对象 |
| 无 single source of truth | ❌ 仍有多处逻辑 | ✅ RolePushPolicy 集中 |
| 难以查询 | ❌ config_json.json_extract | ✅ 简单 SQL 查询 |
| 无验证机制 | ❌ 绑定无效不可知 | ✅ verified_at 标记 + verify API |
| 扩展性差 | ❌ 仍然单渠道 | ✅ 多渠道框架（feishu, wecom, slack, email） |

**预期效果**：
- 推送不再混乱（已通过 P0 实现）
- 配置可管理（新 API + UI）
- 系统可扩展（支持多渠道）
- 故障可诊断（审计日志 + 验证）
