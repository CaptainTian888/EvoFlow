**EvoFlow v1.1.1 — 浏览器内嵌面板能力补齐 / Computer Use 显示链路打通 / 会话停止可靠性修复 / 插件目录与性能优化**

本版覆盖自 **1.1.0** 以来合并进主线的全部用户可感知变更。

### 新增

- **node_repl Playwright 命令面**：domSnapshot / click / fill / type / press / selectOption / textContent / getAttribute / isVisible / count / evaluate / waitFor* 等；locator 链展开为叶子操作
- **浏览器意图检测**：纯数据处理 JS 不再自动拉起浏览器面板；代码中含浏览器 API 才展开
- **CUA 预览卡**：Computer Use 结果显示目标应用徽标 + 截图灯箱；AG-UI 事件贯穿；ZCode 工具渲染器
- **浏览器 URL 安全**：chrome-error:// / chrome:// 等内部错误页不再写回地址栏造成死循环
- **浏览器 tab history + 导航**：后退 / 前进 / 重载按钮 + favicon + 页面标题
- **浏览器 zoom**：Ctrl+滚轮 / 捏合缩放 + toolbar 实时显示比例 + 预设（fit/50/67/75/100/125/150/200）
- **浏览器 embed 跨平台编译**：macOS / Linux CI 可过（嵌入能力仍为 Windows WebView2）
- **多会话浏览器隔离**：每个会话独立保存浏览器 tab；后台会话导航不干扰当前 UI
- **zcode_port 工具 + background bash**：从 ZCode 移植的后台任务 / glob / grep / 通知等工具
- **image staging**：工具截图自动进入下一轮视觉上下文，无需手动 view_image
- **scrollbar reveal**：macOS 风格滚动条显隐
- **聊天摘要浮动卡**：三态（隐藏 / 气泡 / 浮动卡）+ 缩放动画 + 与右栏互斥
- **全局插件目录**：进程内缓存 + 订阅模式，对话与首页预加载
- **STOP-TRACE 取消补丁**：修复长任务（>240s）点停止后「已停还在跑」
- **bash PowerShell 路由**：PowerShell cmdlet 直接走 powershell 不走 Git Bash（省时 + 不报错）
- **node_repl 窗口隐藏**：node.exe 不再弹出黑窗
- **CUA PNG 归一化**：JPEG 截图转真 PNG + 宽高元数据，修复坐标计算错误

### 变更

- 流式结束后自动折叠执行过程，只留最终正文
- 插件市场暂隐藏未迁移的 MCP / Skills Tab
- node_repl tool_call_id 注入 schema（LangChain 自动填充）
- computer-use 运行时提示：截图自动进上下文，坐标用截图像素
- 插件图标路径改写为 Gateway 绝对地址
- embed 贴位统一 HWND_TOP（修复 park 后右侧空白）
- 统一日志重命名 `插件控制日志.log` + MCP 全量 I/O 日志

### 修复

- CI：vendor package.json 被 .gitignore 排除导致构建失败
- 知识库：内置知识库灰点 + 索引状态横幅误报
- 模型：thinking.type=disabled 被拒 400 时剥参重试
- 工具审批：挂起时审批卡消失无按钮 + 摘要文案
- 浏览器嵌入：overlay z-index + setBounds 失败重建 + 坐标
- CDP：Runtime.evaluate awaitPromise + 不再阻塞 4s
- node_repl bridge：newTab 无 url 不报错 + attachTab 契约 + 错误回显

### 性能

- 会话列表：trailing refresh 替代 do-while + 单行同步不刷全表 + 后台 bash 门控轮询
- 文件预览：连续无变化后停轮询 + 避免会话轮询触发反复 read-file
- 流式性能：移除诊断日志 + 告警阈值调高

### 覆盖安装即可

无数据迁移。从 **1.1.0** 覆盖安装至 **1.1.1**。