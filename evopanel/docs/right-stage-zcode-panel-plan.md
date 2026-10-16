# 右栏改造：按 ZCode Side Pane 收成一套标签

> 状态：**阶段 A + 首页/加号/会话缓存已完成**（文件/终端/摘要进标签见阶段 B/C）
> 对照源码：`ZCode/packages/ui/src/lib/workspaceSidePane.ts`、`ZCode/packages/ui/src/app-shell/AnimatedSidePanePanel.tsx`
> 现状锚点：`EvoFlow/evopanel/src/lib/right-stage/`、`EvoFlow/evopanel/src/react/components/BrowserPanel.tsx`、`EvoFlow/evopanel/src/react/ChatApp.tsx`（约 12711、16209 行）

---

## 1. 结论

右栏只保留一套模型：**一份有序标签列表 + 一个外壳 + 按 `kind` 挂内容**。

- 标签只在被打开后出现。关掉一页只删这一页。
- `BrowserPanel` 退回 `browser` 这一种内容，不再当整栏外壳。
- 文件预览、终端从弹层收成标签。Info Rail 不再和右栏互斥抢同一个槽。
- 已有的 `rightStageStore.tabs` 继续当唯一状态。不新造第二套 store。

ZCode 里对应的就是 `WorkspaceSidePaneState`（`tabs` + `activeTabId`）和 `AnimatedSidePanePanel` 里按 `tab.type` 分支。EvoFlow 的 `RightStageSnapshot.tabs` / `activeKey` 已经是这个形状，缺的是外壳真的消费这份列表。

---

## 2. 从 ZCode 原样拿走的合同

这些行为是目标，不是风格参考。

| 合同 | ZCode | EvoFlow 落点 |
|---|---|---|
| 状态只有列表和激活项 | `WorkspaceSidePaneState` | 继续用 `RightStageSnapshot.tabs` + `activeKey`。`surface` 只是激活项的投影，给旧调用过渡，新代码读 `tabs` |
| 打开 = 插入或激活，不替换整栏 | `openBrowserSidePane` / `openCodeViewerSidePane` / `openTerminalSidePane` | 全部走 `rightStageStore.show`。同 key 再打开只激活并更新 `data` |
| 关闭一页 | `closeSidePaneTab` | `closeTab(key)`。禁止用 `hideAll()` 当单页关闭 |
| 外壳不认识具体业务 | `AnimatedSidePanePanel` 只按 `type` 分发 | 新外壳 `RightStagePanel` 只按 `kind` 分发 |
| 非当前页保持挂载 | `TabsContent forceMount` + `hidden` | 浏览器、终端、写入流 `forceMount`。纯展示页（导图、工作流、摘要）可在失活时卸载 |
| 浏览器 guest 不跟面板折叠一起拆 | `shouldMountSidePaneContent` | `browser` 标签还在时，右栏收起也保留 webview |
| 空列表 = 槽位宽度 0 | `collapsedSize: 0px` | `tabs.length === 0` 时不渲染右栏，不拿别的面板填这个洞 |
| 身份稳定 | `kind` + 业务 id | key 继续是 `` `${kind}:${id}` ``。同 kind 多开必须用不同 `id`（文件路径、终端 id、浏览器 tab id） |

不照搬的部分：ZCode 的对话 owner / workspace 可见性过滤、workflow 一串 kind、Git review。EvoFlow 第一期不做对话级隔离；标签跟当前窗口走，切会话时沿用现在的显式关闭，不在 store 里做 owner 过滤。

---

## 3. 目标结构

```
ChatApp 主列
  └─ 宽度槽（有标签才占宽，PanelResizeHandle）
       └─ RightStagePanel          外壳：标签条、排序、关闭、加号
            ├─ kind=browser        BrowserPanel（只有网页内容 + 引擎内的页面标签）
            ├─ kind=workspace-browse / write
            ├─ kind=file           现 WorkspaceFilePreviewModal 的正文
            ├─ kind=terminal       现 TerminalToolDetailModal 的正文
            ├─ kind=collab-workflow
            ├─ kind=mind-map
            ├─ kind=summary        现 ChatSummaryPanel（Info Rail）
            ├─ kind=platform-feedback
            ├─ kind=news-dashboard
            └─ kind=web-embed      仅扩展应用（带 extensionId）
```

标签条只渲染 `snapshot.tabs`。没有「永远在的浏览器 / 工作流 / 思维导图」芯片。

浏览器引擎内部的多页面仍然是 `BrowserPanel` 自己的子标签，不升格成 right-stage 标签。这和 ZCode 一致：side pane 一个 terminal 标签里只有一个 shell，不再套第二层业务标签；浏览器页面标签是浏览器内容的内部状态。

---

## 4. Kind 清单

| kind | id 规则 | 第一期 | 内容组件 | 打开入口 |
|---|---|---|---|---|
| `browser` | `primary`（全窗口一个浏览器面板） | 保留 | `BrowserPanel` | 顶栏地球、browser 工具、`ensureBrowserStage` |
| `workspace-browse` | `primary` | 保留 | `WorkspaceFileTree` | 顶栏文件夹 |
| `write` | `primary` 或 `streamId` | 保留 | 同一棵文件树的写入预览 | `decideRightStage` + `openWriteStream({ auto: true })` |
| `file` | 工作区相对路径 | **新增** | 从 `WorkspaceFilePreviewModal` 抽出的预览正文 | 文件树、消息里的文件链接 |
| `terminal` | 工具调用 id 或会话终端 id | **新增** | 从 `TerminalToolDetailModal` 抽出的正文 | 进程行、终端工具卡片 |
| `collab-workflow` | `primary` | 保留 | `CollabExecutionPanel` | 现有工作流开关 |
| `mind-map` | `primary` | 保留 | `KnowledgeMapPanel` | 现有导图开关 |
| `summary` | `primary` | **第二期** | `ChatSummaryPanel` | 现有 Info Rail 开关 |
| `platform-feedback` | run / entry id | 保留，改挂到外壳 | `PlatformFeedbackKind` | 平台工具结果 |
| `news-dashboard` | `primary` | 保留，改挂到外壳 | `NewsDashboardKind` | 现有入口 |
| `web-embed` | `extensionId` | 仅扩展 | `WebEmbedKind` | 扩展菜单 |
| `artifacts` | — | **继续禁止** | — | store 里 `show('artifacts')` 保持直接 return |

`file` 与 `workspace-browse` 分开。浏览是文件树，打开某个文件是另一页。ZCode 里对应 `code-viewer`，不是把文件塞进树面板。

Diff 第一期仍走 `FileEditDiffModal`。等 `file` 标签稳定后，再决定 diff 是 `file` 的一种 data，还是单独的 `diff` kind。

---

## 5. 外壳职责（对照现在的三套 UI）

新建 `src/react/components/RightStagePanel.tsx`，吸收现在散在三处的事：

| 现在 | 之后 |
|---|---|
| `BrowserPanel` 写死 surface 芯片，关一页调用 `hideAll()` | 删除这段。关闭按钮调用 `closeTab` |
| `ChatApp.renderRightStageBody` + `bodySlot` 造一张 `data: {}` 的假 surface | 删除。外壳把 store 里的真实 `RightStageSurface` 交给内容 |
| `RightStageShell` 按注册表渲染，但 ChatApp 没挂它 | 注册表保留，由 `RightStagePanel` 调用 `getRightStageKind`。未注册的 kind 走 `renderLegacy`，最后才是 `UnknownStageKind` |
| `RightStageTabOverview`、`rightStageTabLayout.ts` 没人用 | 标签条溢出和总览接到这套外壳上，或删掉。不要留第三套标签算法 |
| `surfaceLegacyFlags` 把「激活」说成「打开」 | 布尔值改为「tabs 里是否存在该 kind」。激活与打开分开 |

`ChatApp` 右侧槽变成：

```tsx
{tabs.length > 0 ? (
  <>
    <PanelResizeHandle ... />
    <RightStagePanel tabs={tabs} activeKey={activeKey} onCloseTab={...} />
  </>
) : null}
```

不再写 `rightStageOpen ? <BrowserPanel/> : infoRailOpen ? <ChatSummaryPanel/>`。

布局宽度继续用现有 `rightPanelWidthPx` / `clampRightPanelWidth`。宽度跟「有没有标签」走，不跟某一种 kind 走。`defaultLayoutForKind` 只在**该 kind 第一次把右栏从空撑开**时给默认宽度，用户拖过之后记住像素，切换标签不重置宽度。

---

## 6. 打开 / 关闭规则

1. `show` 仍是唯一写入。调用方传 `kind`、`id`、`title`、`data`。
2. 用户钉住（`rightStageUserPinnedRef`）的含义改成：自动决策不得**切换激活项**，不是不得新增标签。后台可以插入未激活标签。
3. 本轮关掉过的 kind（`dismissedRightStageKindsRef`）只阻止**自动**再次 `show`。用户按钮不受影响。
4. `decideRightStage` 保留，但 `action: 'show'` 的结果必须是 `show` 一个标签，禁止在 ChatApp 里再直接改一套 open flag。
5. `hide(id)` 的「id 对不上就关激活项」兼容逻辑，新外壳不要再依赖。关闭一律带完整 key。
6. `hideAll()` 只留给「用户收起整栏」这一个按钮，并且要先把当前 tabs 写入 `recentClosed`，以便总览恢复。单页 × 不准调用它。
7. 浏览器收起：`closeBrowserStage` 只 `closeTab('browser:primary')`。webview 的销毁跟标签关闭走，不跟右栏显隐走。

---

## 7. 实施清单

### 阶段 A — 外壳换骨（不改内容能力）

- [x] 新增 `RightStagePanel`：读 `tabs`，Radix 或现有 tab 结构，`forceMount` 浏览器。
- [x] 标签条数据源改为 `snapshot.tabs`。拖拽调用已有 `reorderTab`。
- [ ] `register-kinds.tsx` 补上 `workspace-browse`、`write`、`mind-map`、`collab-workflow`（阶段 A 仍经 `renderContent` / `renderRightStageBody` 注入会话态 props）。
- [x] `ChatApp` 右侧槽改挂 `RightStagePanel`。删掉 `bodySlot`。
- [x] `BrowserPanel` 去掉 surface 芯片、`hideAll`、`activeKind` 分支和诊断 `console.log`。它只在 `kind === 'browser'` 时挂载。
- [x] 单页关闭改为 `closeTab`。顶栏地球 / 文件夹：已存在则激活，再点一次关闭**这一页**。
- [x] `workspacePanelOpen` 等标志改为「列表中存在」，避免切到浏览器时文件树被当成已关闭而拆掉状态。
- [x] 删掉无人引用的 `RightStageExtensionsToolbar` import；总览接到外壳搜索按钮。

验收：同时打开浏览器和工作区，两条标签都在；关浏览器，文件树还在；关最后一页，右栏宽度归零；平台反馈和扩展网页能出现在同一条标签上。

### 阶段 B — 文件与终端进标签

- [ ] 新增 `file` kind。`openWorkspaceFilePreview` 改为 `show({ kind: 'file', id: path, data: { path, name } })`。
- [ ] `WorkspaceFilePreviewModal` 降为无标签时的兜底，或直接移除挂载。同一路径重复打开只激活。
- [ ] 新增 `terminal` kind。进程行和终端工具不再只开 `TerminalToolDetailModal`。
- [ ] 终端进程所有权不要放在面板组件的卸载上：面板失活只隐藏，关闭标签才停会话。对齐 ZCode `sidePaneTerminalSessionRegistry` 的 detach / release。

验收：从文件树打开两个文件得到两页；打开终端再切回文件，终端会话还在；关掉终端页后进程释放。

### 阶段 C — Info Rail 成为一页

- [ ] `summary` kind 挂 `ChatSummaryPanel`。
- [ ] 去掉 `rightStageOpen ? … : infoRailOpen ? …` 互斥。
- [ ] Info Rail 开关 = 打开或激活 `summary:primary`，再点关闭该页。
- [ ] 产物继续只在摘要页里展示，不恢复 `artifacts` kind。

验收：浏览器和摘要可以并存；关掉浏览器不会自动弹出摘要；摘要页里的产物、进程、智能体行为与现在一致。

### 阶段 D — 清兼容层

- [ ] ChatApp 里散落的 `setWorkspacePanelOpen` / `setCollabExecPanelOpen` 收成 `show` / `closeTab`。
- [ ] `surface` 投影只留给还没改的订阅方，新代码禁止再根据 `surface.kind` 推断「右栏里有什么」。
- [ ] 补测试：`closeTab` 不清空其它页；`hideAll` 仅整栏；`file` 按 path 去重；`artifacts` 仍被拒绝。现有 `tests/decide-right-stage.test.js`、`tests/right-stage-tab-layout.test.ts` 保持通过。

---

## 8. 不要在阶段 A 做的事

- 不改浏览器传输（WebView2 / iframe / CDP）。
- 不把浏览器内部的网页标签拆成 right-stage 标签。
- 不做 ZCode 那套按对话 owner 过滤可见标签。
- 不把 diff、Git review 放进右栏。
- 不改 `decideRightStage` 的产品规则（谁该自动弹出），只改它的落地方式：弹出 = 加一页。

---

## 9. 阶段 A 的文件落点

| 动作 | 文件 |
|---|---|
| 新增外壳 | `src/react/components/RightStagePanel.tsx` |
| kind 注册补全 | `src/react/right-stage/register-kinds.tsx` |
| 状态 API 已够用，只收紧关闭语义 | `src/lib/right-stage/right-stage-store.ts` |
| 布尔语义 | `src/lib/right-stage/use-right-stage.ts`、`src/react/hooks/useRightStageChatBridge.ts` |
| 卸掉外壳职责 | `src/react/components/BrowserPanel.tsx` |
| 换槽位 | `src/react/ChatApp.tsx` 的 `renderRightStageBody` 与约 16209 行 |
| 溢出 / 总览 | `src/react/components/rightStageTabLayout.ts`、`RightStageTabOverview.tsx` |
