# 工作汇报问题根本原因分析

## 事件时间线

```
21:36:54  你发送：两个抖音视频链接（Josh的AI笔记 + SuperCC 口播）
          ↓
          系统检测：有新的用户输入 (raised_by: xiaomi)
          ↓
21:36:54  自动创建任务：「拆解抖音视频 x2」
          assigned_to: douyin-analyst
          source: chat
          rationale: "小V乐于派任务"
          ↓
21:38:55  douyin-analyst 开始执行
          ↓
22:01:37  小V 进行了任务调度轮次 (dispatch round)
          ↓
22:02:21  任务完成 (completed_at)
          status = "completed"
          progress = 100
          ↓
22:02:32  系统触发 wrap_digest 推送 ← 就是这条消息
          reason: completed_count = 1
```

---

## 为什么会自动推送汇报？

### 触发逻辑

在 `push_wrap_digest_card()` 中：

```python
def should_send_wrap_digest(role, hour_of_patrol):
    """Check if wrap_digest should be sent."""
    # 1. 是否在值班时间？
    # 2. 是否有工作项变化？
    #    - completed_count > 0
    #    - failed_count > 0
    #    - pending_approval_count > 0
    # 3. 是否禁用了 feishu？ (approval_channels)
```

你的情况：
- ✅ 时间：22:02（正常工作时间）
- ✅ 条件：`completed_count = 1`（有 1 个完成的任务）
- ✅ 渠道：douyin-analyst 的 feishu 启用了

### 问题：这个自动任务创建是否合理？

**是否应该这样自动派任务？**

当前系统的行为：
- 用户给 small talk（两条视频链接）
- 系统理解为"工作请求"
- 自动创建任务并派给 douyin-analyst

**这有两种理解**：

#### 理解 A：符合预期（推荐的系统行为）
- 用户就是要求 douyin-analyst 拆解这些视频
- 系统正确地解析了意图
- douyin-analyst 完成了工作
- 汇报是对完成工作的确认

#### 理解 B：过度触发（可能的问题）
- 用户只是"想聊天/分享"，不一定要求系统处理
- 系统不应该把每条消息都理解为工作请求
- 导致任务创建太频繁、汇报太多

---

## 现实问题

目前的实现倾向于"理解 B"——**过度触发**。

**症状**：
- 任何发送给 douyin-analyst 的内容都可能触发任务
- 完成后自动推送汇报
- 用户没有明确表示"这是一个任务"

**改进方向**：

### 方案 1：用户显式请求（最安全）
```
用户输入：@douyin-analyst 拆解这个视频 https://...
         ↓
         系统识别 mention + 动词 → 这是一个任务请求
         ↓
         创建任务 + 最后推送汇报
```

### 方案 2：意图识别更精准（中等）
```
系统分析输入：
  - 是否包含 URL？
  - 是否包含动词（拆解、分析、查找）？
  - 是否是陈述句而不是感叹句？
  ↓
  只在高置信度时创建任务
```

### 方案 3：支持用户配置（快速）
```
douyin-analyst 的配置中：
  auto_task_from_chat: true|false   (默认 false)
  auto_report_on_complete: true|false (默认 false)
```

---

## 立即可改进的地方

### 1. 汇报的去向问题

当前：自动汇报到飞书（因为 approval_channels 有 feishu）

问题：用户可能不希望每个小任务都推汇报

**改进**：
```sql
-- 只对"重要任务"推送汇报
SELECT * FROM evoflow_collab_tasks
WHERE 
  status = 'completed'
  AND importance IN ('high', 'medium')  -- 新增字段
  AND agent_code = 'douyin-analyst'
```

### 2. 汇报的内容

当前：只显示计数 `{"completed": 1}`

问题：无法知道具体完成了什么

**改进**：
```json
{
  "completed": 1,
  "tasks": [
    {
      "name": "拆解抖音视频 x2",
      "started": "21:38:55",
      "completed": "22:02:21",
      "duration_min": 24,
      "status": "success"
    }
  ]
}
```

### 3. 汇报的频率

当前：任何 completed task 立即推送

问题：小任务太频繁

**改进**：
```python
# 选项 A：按固定时间汇报（而不是立即）
if hour_of_patrol % 2 == 0:  # 每 2 小时汇报一次
    send_wrap_digest()

# 选项 B：按任务重要性汇报
if completed_count >= 3 or failed_count > 0:  # 只有 3+ 任务或失败才汇报
    send_wrap_digest()
```

---

## 你的选择

### 如果这是**符合预期的行为**：
✅ 系统工作正常  
✅ douyin-analyst 完成任务  
✅ 汇报有道理  
✅ 不需要改动

### 如果你**不希望自动生成这些汇报**：
需要改动的地方：
1. 修改 `push_wrap_digest_card()` 的触发条件
2. 或改 douyin-analyst 的 `approval_channels` 禁用 feishu
3. 或对自动任务创建进行限制

---

## 推荐的下一步

### 短期（1 周内）
1. 确认：用户是否想要这种自动任务创建？
2. 确认：完成后是否总是要汇报？
3. 调整触发条件或配置

### 中期（P2）
1. 给 douyin-analyst 配置选项：
   - `auto_task_creation: true|false`
   - `auto_report_threshold: 任务数量或时间间隔`
2. 改进汇报内容（显示具体任务而不只是计数）
3. 改进汇报频率（防止过度推送）

---

## 总结

这不是"诡异的无缘无故的汇报"，而是：

```
你的输入 → 系统自动派任务 → Agent 完成 → 系统推汇报
           (正常流程)        (正常流程)  (符合设计)
```

**问题是**：这个自动流程是否应该对所有消息都触发？

**答案**：取决于你的使用意图。

如果需要改动，提交一个 issue，说明：
1. 希望什么时候创建自动任务（显式请求 vs 隐式推断）
2. 希望什么时候推送汇报（立即 vs 定时 vs 条件触发）
3. 汇报的目的是什么（确认完成 vs 跟踪工作量 vs 其他）
