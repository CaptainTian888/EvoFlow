**EvoFlow v1.0.9 — UI 扩展注册表、技能路由注册与 doctor 自检**

### 用户可见

- **UI 扩展注册表 API**：新增 `/api/ui-extensions/*` 网关路由，AI / 脚本可以像面板一样注册 / 启停 / 卸载扩展；面板会即时重读 registry，写入后无需重启
- **Tauri 端 ui_extensions 命令**：与网关对齐 registry / manifest / suite 三层读写，支持 `link`（不复制只登记路径）安装；兼容 PowerShell 5.1 写出的 UTF-8 BOM 与单对象 registry
- **`evoflow doctor` 命令**：本机环境自检，覆盖 SQLite 锁与 WAL 残留、Python 残留进程、技能根目录错位、`EVOFLOW_*` 环境变量、网关运行时——CLI 卡死 / 技能装了不生效 / venv python 启动慢的常用排查一站搞定
- **技能路由注册后端**：网关侧按角色挂载技能，提供可调用的 HTTP 入口
- **主窗口 Streamdown 接管**：流式 markdown 渲染统一走 Streamdown，文件 chip / 协议白名单 / 表格放大 / 代码块分行等交互一致
- **流式结束自动折叠执行过程**：流结束后只保留最终正文卡片，长任务不再被中间执行细节占据屏幕
- **`evoflow log files` 命令**：列出当前 profile 全部日志文件路径与会话 ID
- **桌面端默认优先直连 API**：与开发环境一致，免去网关反代握手，启动即可用
- **会话列表流式探针**：诊断面板里能看到每个会话的 SSE 状态 / 缓冲水位
- **流式多维性能监控（streamperf）**：默认开启，长任务可看到每 delta 各阶段耗时与全面板卡顿监测

### 修复

- 聊天：长思考出现两个思考块（连续 reasoning piece 合并）、折叠态把待授权工具藏掉、流式尾窗 / 合并行齿轮熄灭 / 60s 自愈把 live 视图打回 DB 视图的三处根因、`RUN_FINISHED` 帧 reducer 崩溃（`TypeError: state.timeline`）、编辑用户消息时图片增删不同步、流式过程卡片化后正文分段与多轮新流一闪而过
- Markdown：内联 hashtag / 全角括号行 / 表格行误判为标题、URL 编码换行、false-positive heading
- 通道：企业微信图文混合消息的端到端通路与回退路径；未绑定角色的飞书推送误发
- 加载：Windows `select()` FD 耗尽（`loading_extended` 重试打爆 socket）、`loading_extended` 缺 v4 不再卡 503、`/runs/stream` 失败回退到 `/runs/wait`
- 渲染：`react-vlist-scroller` 滚动不丝滑 + 滚动条 thumb 跳动、`fastdom` / `fastdom-promised` 桩与 mermaid 11.17+ ESM 互操作、Vite 旧 dep 缓存导致 `fastdom` 桩回归
- 工具：agent 模式下 `platform` / `panel_set` 被错误移除恢复；`task_tool` 不再把被禁的 mandatory 协作工具塞进 `disallowed_tools`
- 知识库（owned KB）：重建索引期间搜索不再断流；`staged chunk` 分配串行化避免竞争
- 视觉镜像 head 行去重 / 行级 `ui-display-visual.log` 流水
- 桌面端 health 探测应打网关基址而非页面 origin；工作区视图会话列表漏掉未绑定会话；内置 lazy langgraph 请求转发未剥离挂载前缀
- 模型：限流等瞬时不可用标记自动过期；Anthropic 原生模型请求超时参数映射；未指定 `thinking` 时跟随模型默认
- `mergeSoftHistoryFetch` `curLast` 作用域回退导致的运行时 `ReferenceError`；右侧舞台折叠时 surface 未干净关闭的残留
- 主动角色（smart-employee）：未绑定飞书推送时不再被误发

### 版本与安装

- 桌面端 / 面板 / 后端 / harness 统一 **1.0.9**
- 安装包名：`EvoFlow_1.0.9_x64-setup.exe`（macOS 对应 DMG）

### 升级建议

- 建议从 1.0.8 覆盖安装至 1.0.9
- 本版主要为功能新增（ui_extensions / skills 路由 / doctor）+ 1.0.8 之后累积的流式与渲染回归修复，无数据迁移
