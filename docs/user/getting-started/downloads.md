# 下载与安装

> **先分清智能体和员工**
>
> 1. **区别**：智能体管「会什么」（人设、模型、工具、技能、连接器 MCP）。员工管「何时主动干」（岗位、职责、部门与上级、上班时间、转交审批、工作空间、绑定知识库、预算）。聊天里 @ 智能体不会自动值班。
> 2. **员工能配什么**：加人时填岗位名称、职责、部门、上级、知识库；更多设置里有能力来源、工作空间、关注子路径、工作模型、转交审批（全自动 / 平衡型 / 谨慎型）、自动上班。编辑岗位还可配工作方式、模型思考、系统提示词注入、知识库检索和预算。工具、技能、连接器到「智能体」页改。
> 3. **怎么操作**：侧栏「员工」→「加人」→ 填岗位和至少一条职责 →「确认加人」→ 打开自动上班，或点「现在开始工作」，急活用小V 派活。交工后到任务中心确认或打回。字段见 [智能体员工](../guides/configuration/smart-employees.md)。

> **想开始用？按你的情况选一种方式**：
>
> - **桌面客户端**（推荐）：去 GitHub Releases 下载安装包，Windows/macOS/Linux 都支持，双击安装即可
> - **开发者自托管**：有 Python 3.12+ 和 Node.js 22+？用 `make config && make install && make dev` 启动
>
> 下载完推荐先看[5 分钟快速上手](quick-start.md)开始体验。 [[quick-start|5 分钟快速上手]]

## 桌面客户端

**桌面客户端** 的安装包与 EvoFlow 本体一并发布在 **[EvovexAI/EvoFlow Releases](https://github.com/EvovexAI/EvoFlow/releases)**。

### 下载哪个文件？

在 Releases 页找到最新版本，展开底部的 **Assets** 列表，按你的系统选：

| 系统 | 文件名示例 | 说明 |
|------|-----------|------|
| **Windows** | `EvoFlow_Setup_x.x.x_x64.exe` | 安装程序，双击运行 |
| **macOS** | `EvoFlow_x.x.x_x64.dmg` | 磁盘映像，安装后拖到 Applications 文件夹 |
| **Linux** | `EvoFlow_x.x.x_x64.AppImage` | 下载后 `chmod +x` 即可运行 |

> 如果系统提示"无法验证开发者"，macOS 用户去「系统设置 → 隐私与安全性」中允许运行；Windows 用户点击"更多信息"后再点"仍要运行"即可。

### Linux 没有找到安装包？

官方 Releases 暂未固定提供 Linux 产物时，可从源码自行构建桌面端（免安装二进制 / deb），步骤见 [在 Linux 上构建桌面端](build-linux.md) [[getting-started/build-linux|在 Linux 上构建桌面端]]。

### 安装后做什么

打开应用，在 **设置 → 模型** 中配置 API 密钥即可开始使用。详细界面说明见 [桌面端使用指南](../guides/configuration/evopanel-guide.md) [[guides/configuration/evopanel-guide|桌面端使用指南]]。

## 开发者自托管

如果需要从源码部署后端，请参考 [安装说明](installation.md) [[installation|安装说明]]。

---

## 相关阅读

- [[getting-started/quick-start|5 分钟快速上手]] — 安装后开始体验
- [[getting-started/installation|安装指南]] — 开发者自托管部署
- [[tutorials/configure-models|配置模型]] — 配置 API 密钥与模型
- [[guides/configuration/evopanel-guide|EvoPanel 指南]] — 桌面端各面板入口
