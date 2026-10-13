# EvoFlow Proactive Push 问题修复总结

## 问题描述

你遇到的现象：
1. **17:04** 收到一条空工作汇报（看板无派发任务、无用户提问）
2. **所有员工的值班汇报都推到你的"视频拆解"对话**
3. 感觉推送机制混乱，设计有问题

## 根本原因分析

### 问题 1：空工作汇报也会推送（已修复）
**根因**：
- `_is_idle_patrol_summary` 的 marker 列表不完整，缺少"收工"、"没有派给"等关键词
- `push_wrap_digest_card` 的过滤逻辑有误：`think_summary` 有文字（解释为什么没活干）就放行

**修复**：
- ✅ 加 4 个 markers：「没有派给」、「没有用户提问」、「按规矩不空建单」、「收工」
- ✅ 改进过滤：只要任务计数全零（completed=0, pending=0, failed=0, executing=0），就 skip，不看 `think_summary`

### 问题 2：所有员工推到同一个 chat（已修复）
**根因**：
```python
def resolve_role_feishu_target(role):
    # 1. 检查 role.config.feishu_open_id（通常为空）
    # 2. 都为空 → 调用 resolve_push_target(push_target_id="")
    # 3. 空字符串 → fallback 到全局默认 chat（你的视频拆解对话）
    # 结果：45 个 role 都推到同一个 chat！
```

45 个 role 中，**只有 1 个（douyin-analyst）有绑定**。

**修复（分两层）**：

#### 层 1：代码改动（已完成）
- ✅ 改进 `resolve_role_feishu_target`：按 `agent_code` 查找各自的 chat
- ✅ 如果没有绑定，返回 None（而不是 fallback）

#### 层 2：数据库改动（已完成）
- ✅ 将 45 个无绑定的 role 的 `approval_channels` 改成 `["desktop"]`
- ✅ 禁用 feishu 推送，只保留本地通知

**现在的状态**：
```
48 个 role（包括禁用的）
├─ douyin-analyst: feishu 启用 + 有 open_id 绑定 ✓
├─ xiaomi: feishu 禁用（原本设置）
└─ 46 个其他: feishu 禁用（P0 修复刚禁的）
```

### 问题 3：架构设计缺陷（根本原因分析）
**症状**：为什么会频发这类问题？

**诊断**：
1. **数据结构分散**
   - 推送配置嵌套在 `config_json` 里（非规范化）
   - 没有单独的 role ↔ push_target 映射表
   - 导致推送配置难以查询、验证、更新

2. **业务逻辑分散**
   - `approval_channels` 控制**是否**推送
   - `feishu_open_id` 和 `push_target_id` 定义**推到哪**
   - `resolve_push_target` 又有一套默认逻辑
   - 三套系统没有统一的"Policy"对象

3. **缺乏类型约束**
   - Python 的 `getattr(..., "") or ""` 让空值无声传播
   - 没有强制验证推送目标是否有效

4. **测试不足**
   - 没有单元测试：role 无绑定 → 不推
   - 没有端到端测试：role A 推到 chat A，role B 推到 chat B

---

## 修复清单

### ✅ P0（已完成，立即修复）

| 项 | 修改 | 文件 | 状态 |
|---|---|---|---|
| 1 | 增加 marker：「没有派给」等 | `feishu_notify.py:360-377` | ✅ |
| 2 | 改进空工作过滤逻辑 | `feishu_notify.py:425-426` | ✅ |
| 3 | 改进 resolve_role_feishu_target，按 agent_code 路由 | `feishu_notify.py:46-90` | ✅ |
| 4 | 禁用 45 个无绑定 role 的 feishu 推送 | `evoflow.db` | ✅ |
| 5 | Gateway 重启，代码生效 | PID 42108 | ✅ |

### 🟡 P1（后续，完整设计改造）

| 项 | 方案 | 预期效果 |
|---|---|---|
| 1 | 创建 `evoflow_role_push_bindings` 表 | 推送配置规范化 + 查询便利 |
| 2 | 实现 `RolePushPolicy` 对象 | 单一真实源，逻辑集中 |
| 3 | 添加绑定有效性检验 | test message 验证 open_id/chat_id 有效 |
| 4 | 前端 UI：role 推送配置管理 | 用户可自行配置 |
| 5 | 监控：推送路由日志 | 可视化推送流向和失败 |

---

## 当前状态 & 预期行为

### 修复前
```
douyin-analyst  →  空工作汇报  →  你的视频拆解对话 ✗
customer-service  →  任何汇报  →  你的视频拆解对话 ✗
dev-backend  →  任何汇报  →  你的视频拆解对话 ✗
... 42 more ...
```

### 修复后
```
douyin-analyst  →  有实际工作的汇报  →  douyin-analyst 的绑定 chat ✓
                   →  空工作汇报       →  [skip，不推] ✓
customer-service  →  任何汇报  →  [skip，feishu 已禁用] ✓
dev-backend  →  任何汇报  →  [skip，feishu 已禁用] ✓
... 43 more ...
```

---

## 下一步建议

### 立即（确认无误）
1. **监控日志**（18:30 后）
   - 检查 `channel-diag.log` 是否还有错误推送
   - 查看新的 wrap_digest 记录

2. **对 douyin-analyst 的测试**
   - 触发一次值班巡检
   - 验证汇报是否推到了正确的地方（而不是你的视频拆解对话）

### 本周（P1 规划）
1. **创建 role_push_bindings 表**
   - 从 config_json 迁移数据
   - 支持 multi-channel（feishu, wecom, slack）

2. **给其他需要推送的 role 配置绑定**
   - 哪些 role 需要飞书推送？建立一个表单
   - 每个 role 对应一个 open_id（或 group chat）

3. **监控告警**
   - 每天检验所有 role 的绑定有效性
   - 推送失败时立即告警

### 长期（架构改善）
- 设计统一的 `Channel Policy` 系统
- 支持多渠道（邮件、钉钉、企业微信等）
- 实现权限级联（global → department → role）

---

## 技术债务总结

这次问题的根本原因是**设计阶段就埋下的债**：
1. 最初假设"推送目标总是存在"
2. 用 `config_json` 存储所有配置（没有规范化）
3. 没有单一真实源（single source of truth）
4. 后来新增功能时打补丁，没有重构

**防止重复的原则**：
- 一个概念 = 一张表（第一范式）
- Policy 对象集中逻辑
- 写测试验证端到端流程
- 定期 audit（bindings 有效性）
