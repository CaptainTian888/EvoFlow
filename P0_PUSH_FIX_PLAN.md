# P0 修复方案：禁用所有无绑定 role 的 Feishu 推送

## 现状
- 45 个 role 无 feishu_open_id / push_target_id 绑定
- 它们会 fallback 到全局默认 chat（你的视频拆解对话）
- 导致混乱

## P0 方案（快速）
逻辑修改 + 数据库实施：

1. **代码改动**：`resolve_role_feishu_target` 遇到无绑定，不再 fallback，直接返回 None
   ✅ 已做

2. **数据库改动**：将所有无绑定的 role 的 `approval_channels` 改成 `["desktop"]`（禁用 feishu）
   目的：明确地关闭推送，而不是依赖代码的 None check

3. **结果**：
   - douyin-analyst → 有绑定，继续推到自己的 chat
   - 其他 45 个 → 推送禁用，只在 desktop 通知

## P1 方案（完整，后续）
创建 role_push_bindings 表，提供管理界面，让使用者能自行配置。

## 现在执行
