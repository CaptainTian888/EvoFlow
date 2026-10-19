**EvoFlow v1.1.0 — 插件 / 浏览器桥接 / MCP / 任务重试，以及审批与嵌入窗口一揽子修复**

本版覆盖自 **1.0.9** 以来合并进主线的全部用户可感知变更（含标签后继续合入、将随本包发出的修复）。

### 新增

- **任务失败步骤重试**：任务列表 / 详情新增「重试失败步骤」（`POST /tasks/{id}/retry`），只补跑 `failed` 子任务；可指定子任务 ID 或重试全部失败步骤；已完成步骤不动
- **任务操作术语**：paused「继续」→「恢复执行」；failed 拆成「重试失败步骤」与「重新执行」（整任务克隆）；详情「再跑一次」→「重新执行」
- **插件系统**：后端 plugins runtime / service / storage / manifest / zip 源；网关 `plugins` 路由；设置页插件管理；聊天侧 PluginPickerModal / PluginQuickPanel；内置 evoflow-guide / skill-kit / hello-command；`bridge_auth` 认证桥接
- **浏览器桥接与内嵌面板**：网关 `browser_bridge` / `cua_bridge`；Tauri `browser_embed` / `browser_embed_bridge` / CDP HTTP；右侧舞台 BrowserPanel 增强；WebView2 嵌进右侧槽位并跟主窗口缩放移动；`node_repl` Playwright 命令面（domSnapshot / click / fill / type / waitFor* 等）与浏览器意图检测；CUA 结果预览卡（应用图标 + 截图灯箱）
- **MCP 服务器管理**：设置页 MCP 管理与市场同步；MCP 连接池复用与缓存
- **右侧舞台标签化**：RightStage 收成 tabs 模型（Terminal / 工作区预览 / 浏览器等），BrowserPanel 不再当整栏外壳；会话级右侧舞台记忆
- **聊天摘要浮动卡**：ChatSummaryPanel 三态（隐藏 / 气泡 / 浮动卡），与右侧舞台互斥展开
- **任务完成通知音**：后台通知可播放提示音，设置内可开关
- **流式追踪调试**：`stream_trace` / `analyze_stream_trace` 与相关文档（排障用）
- **统一日志**：浏览器 / CDP / CUA / node_repl 写入 `插件控制日志.log`；MCP CUA / node_repl 全量 I/O 日志
- **文档与许可**：Claude Code Python SDK 集成指南、zcode 许可说明、介绍页；zcode 第三方许可文件

### 变更

- 删除 `experience_tool.py`，旧经验库迁资产中心扁平 MD
- 知识库 owned 解析 / 嵌入 / pipeline / worker 增强；技能注入中间件与 loader 调整
- 流式结束后自动折叠执行过程，只留最终正文
- 首页加载去掉分阶段 loadPhase 文案，保留单一横幅
- 插件市场暂隐藏尚未迁移的 MCP / Skills 独立 Tab（统一收进插件）
- i18n（en-US / zh-CN）与主题样式随上述能力更新

### 修复

**工具审批**

- 审批面板不再被「工作时长」折叠藏掉；授权暂停时折叠头显示「等待授权」并保持展开
- 多工具待审批时点击后立即显示「已批准 / 已拒绝」回执
- 多轮审批按 tool_call_id 精确匹配宿主，授权间隙折叠防闪烁（approval latch）
- 「始终允许本项目」追溯放行同批已登记的兄弟 pending
- 审批挂起时实时视图保留待授权工具，修复审批卡消失、无按钮
- 摘要文案「曾待授权」→「等待授权」

**聊天 / 流式**

- 折叠头带最后一步；spinner 文案事件化；proactive 活动走 `panel:activity` 控制面广播
- 流式显示行 / MessageVirtualList / 行 memo 在流式 tick 下更稳
- stream-perf 热路径去掉噪音诊断；相位告警阈值上调，减少误报

**浏览器嵌入**

- WebView2 嵌进右侧槽位；CSS 槽位按主窗口客户区缩放；槽位 vs HWND 坐标诊断
- park 后再 show 时抬到主 WebView 之上，避免右侧槽位空白
- setBounds 失败（停靠 / 崩溃）时按 URL 重建 embed 窗口，避免恢复时把页面打成 about:blank
- 嵌入覆盖层与全局弹窗 z-index，避免遮挡错乱
- macOS / Linux 编译桩补齐（跨平台 CI 可过；嵌入能力仍为 Windows WebView2）

**模型 / MCP / 插件**

- 厂商拒绝 `thinking.type=disabled` 返回 400 时实例记忆并剥参重试一次
- MCP 连接池与插件 bridge_auth 相关稳定性修复
- CI 跟踪 `evopanel/vendor/**/package.json`，避免 vendor 包 exports 在 CI 解析失败

**其它**

- 子任务产出 / outcome 判定；流式路由日志与 SSE 归一化；会话仓储与权限预设持久化
- 桌面通知与浏览器桥接坐标相关边角问题

### 版本与安装

- 桌面端 / 面板 / 后端 / harness 统一 **1.1.0**
- 安装包名：`EvoFlow_1.1.0_x64-setup.exe`（macOS 对应 DMG）

### 升级建议

- 建议从 **1.0.9** 覆盖安装至 **1.1.0**
- 无数据迁移；覆盖安装即可
