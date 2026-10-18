# 在 Linux 上构建桌面端

> **先分清智能体和员工**
>
> 1. **区别**：智能体管「会什么」（人设、模型、工具、技能、连接器 MCP）。员工管「何时主动干」（岗位、职责、部门与上级、上班时间、转交审批、工作空间、绑定知识库、预算）。聊天里 @ 智能体不会自动值班。
> 2. **员工能配什么**：加人时填岗位名称、职责、部门、上级、知识库；更多设置里有能力来源、工作空间、关注子路径、工作模型、转交审批（全自动 / 平衡型 / 谨慎型）、自动上班。编辑岗位还可配工作方式、模型思考、系统提示词注入、知识库检索和预算。工具、技能、连接器到「智能体」页改。
> 3. **怎么操作**：侧栏「员工」→「加人」→ 填岗位和至少一条职责 →「确认加人」→ 打开自动上班，或点「现在开始工作」，急活用小V 派活。交工后到任务中心确认或打回。字段见 [智能体员工](../guides/configuration/smart-employees.md)。

> 官方 Releases 目前主要提供 Windows / macOS 安装包。Linux 用户可以用几条命令从源码构建出同样的桌面应用（免安装二进制 / deb）。以下步骤已在 Ubuntu 24.04 上验证通过。

## 环境准备

- Rust（含 cargo）：通过 [rustup](https://rustup.rs) 安装
- Node.js 22+ 与 pnpm 9+
- 系统依赖（Ubuntu 22.04 / 24.04，其他发行版安装对应包即可）：

```bash
sudo apt-get install -y libwebkit2gtk-4.1-dev build-essential libxdo-dev \
  libssl-dev libayatana-appindicator3-dev librsvg2-dev file
```

## 构建步骤

```bash
git clone https://github.com/EvovexAI/EvoFlow.git
cd EvoFlow/evopanel
pnpm install
pnpm tauri build --bundles deb
```

构建产物：

| 产物 | 路径 | 说明 |
|------|------|------|
| 免安装二进制 | `src-tauri/target/release/evoflow` | 直接运行，前端已内置 |
| deb 安装包 | `src-tauri/target/release/bundle/deb/EvoFlow_<版本>_amd64.deb` | `sudo dpkg -i` 安装 |

## 两个实用说明

### 1. 本地构建末尾的更新器报错可忽略

未配置更新器签名密钥（`TAURI_SIGNING_PRIVATE_KEY`）时，构建最后会报
`Unable to find a bundled project for the updater`——此时二进制与 deb **已经生成完毕**，直接取用即可。该步骤仅在官方发布流程（CI 持有签名密钥）中需要成功。

### 2. 连接外部已启动的 Gateway（开发 / 自托管模式）

桌面端默认尝试拉起内置 Gateway。如果你的 Gateway 已经在跑（例如源码开发栈 `make dev`，或自托管部署），可以通过环境变量让桌面端直接连接，不再启动内置 sidecar：

```bash
EVOFLOW_GATEWAY_URL=http://127.0.0.1:8001 src-tauri/target/release/evoflow
```

这种模式下后端服务常驻、桌面窗口随开随关，适合开发调试以及「服务部署在一处、窗口随时开关」的用法。

## 相关阅读

- [[getting-started/downloads|下载与安装]] — 官方安装包下载
- [[getting-started/installation|安装指南]] — 开发者自托管部署
