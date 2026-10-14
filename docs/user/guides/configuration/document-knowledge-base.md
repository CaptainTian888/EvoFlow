# 上传文档（RAG）— 已下线

> **本能力已下线。** 请改用侧栏 **[知识库（Obsidian Vault）](knowledge-vault.md)** [[guides/configuration/knowledge-vault|知识库]]（`#/knowledge/vaults`）。
>
> 旧路由 `#/knowledge` / `#/knowledge/:id` 会自动跳转到知识库页。Agent 请使用 `knowledge(action=…)`，不再提供 `search_knowledge_base`。

零散 PDF/Word 可先放入 Obsidian / Markdown 目录，再连接为知识库；会话级附件仍走聊天 Composer（见 [文件上传](../chat/file-upload.md) [[guides/chat/file-upload|文件上传]]）。

| 能力 | 入口 | Agent 工具 |
|------|------|------------|
| **知识库**（Vault） | `#/knowledge/vaults` | `knowledge(action=…)` |
| **资产中心**（偏好/经验/反思） | `#/assets` | 对话自动整理 / `assets` 工具 |
| **会话文件上传** | 聊天 Composer | 单次会话解析 |

详见 [知识库](knowledge-vault.md) [[guides/configuration/knowledge-vault|知识库]]、[资产中心](asset-center.md) [[guides/configuration/asset-center|资产中心]]。

---

## 开发者备注：gateway 里有两套 knowledge API，不互通

排查「知识库怎么是空的 / AI 读不到」时，先分清你在跟哪套 API 对话：

| API | 体系 | 数据来源 | 谁在用 |
|-----|------|---------|--------|
| `/api/knowledge`（dataset） | 旧「上传文档 RAG」残留（已下线） | `POST /{dataset_id}/sync-local` 等只服务 dataset 本身；新装实例 dataset 为空（`{"items": []}` 属正常） | 旧集成脚本 |
| `/api/knowledge/owned` | **owned Vault 知识库**（现役） | 面板「知识库」页连接的 Obsidian/Markdown 目录，由后端服务管理索引 | 面板知识库页 + AI 的 `knowledge(action=…)` 工具 |

要点：

- **AI 侧 `knowledge` 工具只走 owned Vault**，与 dataset 体系不互通——给 dataset sync 文件对 AI 检索无效。
- 让 AI 检索你的资料：把目录接入面板「知识库」页（owned Vault），或参考 [Obsidian Vault 集成](../integrations/obsidian-knowledge-vault.md)。
- 自动化写入资料也走 owned Vault API（`/api/knowledge/owned/...`），不要往 `/api/knowledge` 塞。

---

## 相关阅读

- [[guides/configuration/knowledge-vault|知识库（Obsidian Vault）]] — 连接本机笔记库的全新方案
- [[guides/configuration/asset-center|资产中心]] — 偏好、经验与反思
- [[guides/integrations/obsidian-knowledge-vault|Obsidian Vault 集成]] — 底层架构与 MCP 细节
- [[guides/chat/file-upload|文件上传]] — 会话级附件解析
