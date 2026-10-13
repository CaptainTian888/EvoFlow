# 两个关键问题的深层分析

## 问题 1：任务派发来源混乱

### 你说的情况
"不是小V派发的，是我在飞书通道上直接跟员工说的，这个任务是他自己创建的"

### 数据库记录显示
```json
{
  "source": "chat",
  "raised_by": "xiaomi",  // ← 系统认为是你发起
  "created_by": null,     // ← 没有记录具体创建者
  "assigned_to": "douyin-analyst",
  "source_channel": "user"
}
```

### 两种可能的场景

#### 场景 A：系统自动识别并创建（当前实现）
```
你在飞书说：           "拆解这个视频..."
                      ↓
系统 NLP 理解：        "用户请求拆解视频"
                      ↓
系统自动创建任务：      task_id=2610131336_403f
                      source="chat"
                      raised_by="xiaomi"
                      ↓
系统自动派给：         douyin-analyst
```

**问题**：系统代表用户创建，不是员工主动创建

#### 场景 B：员工在飞书群里自己创建任务（未正确记录）
```
你在飞书群说：        "需要拆解视频"
                      ↓
员工（douyin-analyst）: "@任务系统 创建任务：拆解视频"
                      ↓
应该记录：             created_by="douyin-analyst"
                      source="agent_self_created"
                      
实际记录：             created_by=null
                      source="chat"
```

**问题**：记录不准确，无法追踪员工的自主行动

### 根本问题

**`created_by` 字段为 null**

- ❌ 如果员工自己创建，应该记录 `created_by: "douyin-analyst"`
- ❌ 如果系统自动创建，应该记录 `created_by: "system"` 或 `created_by: "xiaomi"`
- ⚠️ 目前是 null，无法区分两种情况

### 改进方案

需要改进的地方：

```python
# 在任务创建时，明确记录来源

class TaskCreationSource:
    AGENT_SELF_INITIATED = "agent_self_created"      # Agent 自己创建
    USER_REQUEST_AUTO = "user_request_auto"          # 用户请求，系统代理创建
    USER_REQUEST_EXPLICIT = "user_request_explicit"  # 用户 @agent 明确要求
    SYSTEM_AUTO = "system_auto"                      # 系统自动生成
    SYSTEM_DELEGATION = "system_delegation"          # 系统派发

# 任务表应该记录：
{
    "task_id": "2610131336_403f",
    "created_by": "douyin-analyst",              # 谁创建的
    "creation_source": "agent_self_created",     # 怎么创建的
    "triggered_by": "xiaomi",                    # 谁触发的（如果是自动）
    "raised_by": "xiaomi",                       # 谁提出的需求
    "source_channel": "feishu_group_chat"        # 从哪个通道来的
}
```

---

## 问题 2：完成快但推送晚 - 延迟问题

### 实际时间线

```
时间点分析：
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

21:36:54.39  ├─ 任务创建 (created_at)
             │
             ├─ [延迟 2 分钟 1 秒]  ← ⚠️ 问题 2a
             │
21:38:55.47  ├─ Agent 开始执行 (started_at)
             │
             ├─ [实际工作 23 分钟 26 秒]
             │
22:02:21.52  ├─ Agent 完成工作 (completed_at)
             │
             ├─ [延迟 11.4 秒]  ← ⚠️ 问题 2b
             │
22:02:32.92  └─ 推送 wrap_digest
```

### 问题 2a：创建到开始为什么延迟 2 分钟？

**可能的原因**：

1. **任务队列排队**
   - 系统中其他任务正在执行
   - 这个任务在队列中等待

2. **系统 patrol 循环**
   - 每个 agent 的 patrol 不是实时的
   - 每隔 N 分钟运行一次
   - 任务创建后要等待下一次 patrol 开始

3. **Agent 的热启动时间**
   - Agent 可能在冷启动或重新初始化
   - 需要加载上下文、模型等

**这是问题吗？**
- ✅ 取决于预期
- 如果希望 < 10 秒启动，那这是延迟
- 如果允许 2-5 分钟，那这是正常的

### 问题 2b：完成到推送为什么延迟 11 秒？

**原因可能**：

1. **Patrol 循环检测延迟**
   - Patrol 循环以固定间隔运行（每 30 秒？每 1 分钟？）
   - 任务完成时，下一次 patrol 可能还要等几秒

2. **推送处理延迟**
   - 生成报告
   - 调用飞书 API
   - 等待响应
   - 总共 10+ 秒是合理的

**这是问题吗？**
- ✅ 11 秒对于"立即汇报"来说可能有点晚
- ✅ 但对于"完成后几秒内汇报"来说是可接受的

### 真实的用户感受

从用户的角度：
```
21:36  我说完：拆解这两个视频
       （虽然系统自动派任务，但我不知道）

22:02  员工其实已经完成了
       （大概 26 分钟的工作）

22:02  系统推送汇报
       （但比完成晚了 11 秒）
       
用户感受：为什么莫名其妙就推送了一条？
```

**实际上**：
- 员工 21:38 开始工作，23 分钟后完成
- 系统 11 秒后检测到并推送
- 整个过程实际上是正常的，只是用户不知道任务的来源

---

## 两个问题的关联

```
问题 1 的根本：
  任务来源不清楚 → 用户不知道这是怎么创建的
  
问题 2 的根本：
  推送时机不清楚 → 用户不知道为什么突然推送
  
组合后的用户困惑：
  "为什么突然创建了一个任务？"
  "为什么员工那么快完成了？"
  "为什么突然推送了汇报？"
  
全是"莫名其妙"
```

---

## 完整的改进方案

### 短期改进（记录和追踪）

1. **改进任务创建记录**
   ```sql
   ALTER TABLE evoflow_collab_tasks ADD COLUMN created_by TEXT;
   ALTER TABLE evoflow_collab_tasks ADD COLUMN creation_source TEXT;
   ```

2. **改进推送记录**
   ```sql
   -- 记录推送的具体触发原因
   INSERT INTO evoflow_feishu_push_audit
   VALUES (..., decision_reason='task_completed', trigger_task_id='2610131336_403f', ...)
   ```

3. **改进诊断能力**
   ```python
   # 能够追踪一个任务的完整链路
   def trace_task_lifecycle(task_id):
       return {
           "created": ...,
           "creation_source": ...,
           "started": ...,
           "completed": ...,
           "push_trigger": ...,
           "push_sent": ...
       }
   ```

### 中期改进（用户体验）

1. **在飞书上显示任务来源**
   ```
   任务详情卡片：
   ├─ 标题：拆解抖音视频 x2
   ├─ 来源：xiaomi 在群里提出
   ├─ 创建方式：系统自动
   ├─ 指派给：douyin-analyst
   └─ 状态：已完成
   ```

2. **让用户明确派任**
   ```
   允许方式：
   - "@douyin-analyst 帮我拆解这个视频"  (显式)
   - 直接分享链接                        (可配置是否自动派任)
   ```

3. **改进推送时机**
   ```
   选项 A：更快推送（实时检测完成状态）
   选项 B：汇总推送（每小时一次）
   选项 C：用户选择（设置偏好）
   ```

---

## 你应该确认的问题

向团队确认：

1. **设计问题**
   - 是否应该对所有飞书消息自动创建任务？
   - 还是只有显式提及或特定关键词才创建？

2. **数据问题**
   - 为什么 `created_by` 是 null？
   - 应该如何正确记录任务创建来源？

3. **延迟问题**
   - 2 分钟的启动延迟是否可接受？
   - 11 秒的推送延迟是否可接受？
   - 如果不可接受，需要如何优化？

4. **推送问题**
   - 是否每个完成都要推？
   - 还是只有重要任务推？
   - 推送时是否需要显示任务详情？
