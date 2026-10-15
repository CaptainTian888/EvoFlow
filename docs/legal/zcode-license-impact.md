# ZCode (Apache-2.0) 引入对 EvoFlow 商业化的影响

> 范围：解释 EvoFlow `evopanel/src/zcode-*` 与 `evopanel/vendor/zcode-cua/`
> 七个目录 vendored 自 [zai-org/ZCode](https://github.com/zai-org/ZCode)
> （Z.AI Co., Ltd.，Apache License 2.0）之后，对 EvoFlow 商业化路径、
> 法务合规、客户尽调的影响与应对动作。
>
> 适用读者：EvovexAI 内部、潜在商业客户法务、未来接手此项目的维护者。
> 最后更新：2026-10-15。

---

## 1. 结论（先说结论）

- **Apache-2.0 不会阻碍 EvoFlow 商业化**。Apache-2.0 是 permissive 许可证，
  允许商用、闭源修改、收费、再分发，不需要向 Z.AI 付费。
- **EvoFlow 商业化路径的真正限制来自主许可证
  [PolyForm Noncommercial 1.0.0](../LICENSE)**——任何商业使用（包括自营 SaaS、
  私有化部署、商业插件、衍生产品）都需要
  [cloud@evovexai.com](mailto:cloud@evovexai.com) 书面授权。**这与是否 vendor
  ZCode 无关**。
- **两条许可证并行作用于各自代码段**：
  - PolyForm Noncommercial：作用于 EvoFlow 自研代码。
  - Apache-2.0：仅作用于 vendor 进来的 ZCode 衍生段（见 [NOTICE](../NOTICE)
    中的 `ZCode (Apache License 2.0)` 一节）。
- 已经完成的合规动作见本文件 §4。还需要做的"打包分发时把 LICENSE 一并带出"
  见 §5。

---

## 2. Apache-2.0 条款逐条对照

| 维度 | Apache-2.0 的态度 | 对 EvoFlow 商业化的影响 |
|---|---|---|
| 商业使用 / 销售 / 收费 | ✅ 允许 | 无影响 |
| 修改 / 不公开修改 | ✅ 允许 | 无影响 |
| 闭源再分发 / SaaS | ✅ 允许 | 无影响 |
| 必须保留版权声明 | ✅ 必须 | NOTICE 已满足 |
| 必须保留许可证副本（§4(a)） | ✅ 必须 | `licenses/zcode-APACHE-2.0.txt` 已放 |
| 修改文件需带"已变更"声明（§4(b)） | ✅ 必须 | 七个 vendor 目录下各放了 `THIRD_PARTY_ZCODE.md` |
| 派生作品分发时附 NOTICE（§4(d)） | ✅ 必须 | 仓库根 `NOTICE` 满足 |
| 不得使用 Z.AI 商标做背书（§6） | ✅ 必须 | 我们只在自己的品牌下发布 |
| 专利授权（§3） | ✅ 给下游 | **正向加分**：Z.AI 不能再用 zcode 涉及专利反诉 EvoFlow 侵权 |
| 是否强制开源后续修改 | ❌ 不强制 | 与 AGPL/GPL 不同，可闭源 |
| 是否强制回馈上游 | ❌ 不强制 | 无影响 |

**一句话**：Apache-2.0 是你拿到的"白名单 + 专利盾"，不是"锁链"。

---

## 3. 场景化判断（你可以照着这张表对客户/法务讲）

| 商业化场景 | 是否需要 Z.AI 额外授权 / 付费 | 是否需要 PolyForm 商用授权 |
|---|---|---|
| EvoFlow 自营 SaaS / 云服务 | ❌ 不需要 | ✅ **需要**（cloud@ 协商） |
| 卖给企业做私有化部署 | ❌ 不需要 | ✅ **需要** |
| 拆分 EvoFlow 自研模块独立开源/闭源 | ❌ 不需要 | ✅ 需要（如果仍走 PolyForm） |
| 拆分**含 zcode 衍生代码**的子模块独立发布 | ❌ 不需要，但该子模块**整体**必须保留 Apache-2.0 或更宽松许可证，**不能换锁成 PolyForm Noncommercial** | ❌ 这部分不受 PolyForm 约束 |
| 在 EvoFlow 控制台 / 关于页保留 zcode 致谢 | ❌ 不需要，但要保留 | n/a |
| 被 Z.AI 收购 / 与 Z.AI 合作 | ❌ 不需要 | ✅ 需要 PolyForm 协商 |
| 客户法务索要 SBOM / 三方清单 | ❌ 不需要，但需提供 | n/a |
| 自行决定某天去掉 zcode 依赖 | ❌ 不需要，Apache-2.0 无终止条款，可无限期使用 | n/a |

**关键边界**：含 zcode 衍生代码的子模块一旦独立发布，**不能**用比 Apache-2.0
更严格的许可证"再包一层"。其余情况下，PolyForm 仍然是 EvoFlow 自研部分的
主许可证。

---

## 4. 已经完成的合规动作（2026-10-15）

下列动作已落到仓库；后续每次 vendor ZCode 都应保持：

1. **NOTICE 增加 ZCode 段**：[NOTICE](../NOTICE) 中新增 `ZCode (Apache
   License 2.0)` 一节，含：
   - 版权声明 `Copyright 2026 Z.AI Co., Ltd`
   - Apache-2.0 标准 NOTICE 模板
   - 七个 vendored 路径清单
   - 与 PolyForm 主许可证的并存说明
   - 商标条款
2. **许可证副本**：[licenses/zcode-APACHE-2.0.txt](../licenses/zcode-APACHE-2.0.txt)
   存放 Apache-2.0 完整文本 + EvoFlow 重分发说明（与现有
   `licenses/deerflow-MIT.txt` 风格一致）。
3. **vendor 目录声明**：七个 zcode 目录各放一份 `THIRD_PARTY_ZCODE.md`，
   说明该目录为 EvoFlow 修改过的 ZCode 上游副本，履行 Apache-2.0 §4(b)
   "modified files carry prominent notices stating that You changed the
   files" 要求：
   - `evopanel/src/zcode-ui/THIRD_PARTY_ZCODE.md`
   - `evopanel/src/zcode-shared/THIRD_PARTY_ZCODE.md`
   - `evopanel/src/zcode-rpc/THIRD_PARTY_ZCODE.md`
   - `evopanel/src/zcode-provider/THIRD_PARTY_ZCODE.md`
   - `evopanel/src/zcode-provider-node/THIRD_PARTY_ZCODE.md`
   - `evopanel/src/zcode-services/THIRD_PARTY_ZCODE.md`
   - `evopanel/src/zcode-model-option-map/THIRD_PARTY_ZCODE.md`
4. **`vendor/zcode-cua` 增强**：
   - `package.json` 增加 `licenseFile` 指向仓库内 Apache-2.0 副本。
   - `README.md` 增加 Upstream / License 段。
5. **README 致谢段更新**：
   - 中文 [README.md](../README.md) 致谢段补 ZCode（vendored / 借鉴）。
   - 英文 [README.en.md](../README.en.md) Acknowledgements 同步。
6. **vendor manifest**：`evopanel/scripts/zcode-vendor-manifest.json` 钉住
   上游 commit `29628c9acdb81b703bbd4080c207a0e7ce5e276e`，方便后续增量
   vendor 时可追溯。

---

## 5. 后续要持续保证的事（每次发版前自查）

### 5.1 打包 / 分发清单

任何对外发布物都必须包含：

| 文件 | 原因 |
|---|---|
| `NOTICE` | Apache-2.0 §4(d) + PolyForm 三方共存说明 |
| `licenses/zcode-APACHE-2.0.txt` | Apache-2.0 §4(a) 许可证副本 |
| `licenses/deerflow-MIT.txt` | DeerFlow MIT 许可证副本 |
| `LICENSE` | PolyForm Noncommercial 主许可证 |
| `AUTHORS.md` / `CLA.md` | 自研代码归属与贡献者协议 |

具体到各发布形态：

- **Docker 镜像**：在最终镜像的 `Dockerfile` 里
  `COPY NOTICE LICENSE licenses/ /app/`。
- **桌面版（Tauri）**：把 `NOTICE` / `licenses/` 加入
  `tauri.conf.json` 的 `bundle.resources`，并在前端"关于 / 第三方"页放一份
  NOTICE 摘要。
- **CLI / TUI 发行包**（`pnpm build:zcode` 等价物）：构建脚本里把
  `NOTICE` 与 `licenses/` 拷贝进 `dist/` 子目录。
- **GitHub Release zip/tar**：检查发布流水线包含这些文件。
- **私有化部署包**（tar / installer）：同上。

### 5.2 增量 vendor 时

- 重新生成 `scripts/zcode-vendor-manifest.json`，记录新上游 commit。
- 检查新文件 / 修改文件是否需要更新对应目录的 `THIRD_PARTY_ZCODE.md`。
- 如果 ZCode 上游改许可证到非 Apache-2.0 兼容版本：必须在重 vendor 前
  与法务确认；不建议把变更后版本纳入 EvoFlow 主分支。

### 5.3 客户尽调模板

见附录 A。可直接发给客户法务 / 采购走采购流程。

---

## 6. 常见问题（FAQ）

**Q1：ZCode 改用更严格的许可证会影响我们吗？**
不影响。Apache-2.0 §"版本升级"条款：已经按 Apache-2.0 拿到的代码**永远**
按 Apache-2.0，不能追溯。Z.AI 未来单方面换证（如 SSPL/BSL）不约束你
已经 vendor 的代码副本。

**Q2：我可以直接把 ZCode 衍生代码放到商用闭源产品里卖吗？**
可以。Apache-2.0 允许闭源 + 收费 + 修改；你不需要向 Z.AI 报备、付费或
公开你的修改。PolyForm 主许可证仍然约束你自己的代码，但 ZCode 那部分
不受 PolyForm 影响。

**Q3：EvoFlow 是 ZCode 的 fork 吗？**
不是。EvoFlow 是独立产品。EvoPanel 引入了 ZCode 七个 vendor 目录作为
一部分组件；其他部分（gateway、knowledge-owned、proactive workflow、
plugins、talking-head-recut 等大量自研代码）与 ZCode 无关。NOTICE 中
使用"vendored / 借鉴"而非"基于 / fork"措辞，意在准确表达这一关系。

**Q4：客户问我"EvoFlow 是不是基于 ZCode 二次开发"，我该怎么回？**
参考话术：

  > EvoFlow 是独立产品。在 EvoPanel 桌面端，我们采用了 Z.AI 的开源项目
  > ZCode（Apache-2.0）的部分 UI 与协议代码作为组件级 vendor；同时
  > EvoFlow 自研了 gateway、知识库、proactive workflow、plugin 系统等
  > 大量独立模块。我们与 Z.AI 没有商业 / 股权关系，Z.AI 也不参与 EvoFlow
  > 的产品决策。

**Q5：Apache-2.0 专利授权条款对我有什么好处？**
Z.AI 在 §3 中向所有下游（包括 EvoFlow 与 EvoFlow 客户）授予了"使用 zcode
涉及专利"的非独占、免费、不可撤销的许可。**这意味着 Z.AI 不能用 zcode
相关的专利反过来起诉你侵权**。PolyForm / MIT 都没有这种保护，所以对
EvoFlow 反而是加分项。

**Q6：如果我某天想彻底去掉 ZCode 依赖？**
直接删除 `evopanel/src/zcode-*` 与 `evopanel/vendor/zcode-cua/` 即可，
然后把 NOTICE 中相关段落移入"过往第三方组件"附录（保留历史归属），
不需要其他额外动作。

**Q7：以后还要 vendor 其他 Apache-2.0 项目吗？**
可以。流程就是这次的样子：补 NOTICE 一节、放 `licenses/<name>-*.txt`、
在 vendor 目录根放 `THIRD_PARTY_<name>.md`。

---

## 附录 A：客户尽调可发的"第三方组件合规摘要"模板

```
EvoFlow 第三方组件合规摘要（截至 YYYY-MM-DD）

主许可证：PolyForm Noncommercial License 1.0.0（商业使用须书面授权：
  cloud@evovexai.com）。
完整第三方清单：见仓库 NOTICE 文件。

按许可证分组的第三方组件：

1. Apache License 2.0
   - ZCode（zai-org/ZCode, Copyright 2026 Z.AI Co., Ltd.）
     范围：evopanel/src/zcode-ui, zcode-shared, zcode-rpc, zcode-provider,
           zcode-provider-node, zcode-services, zcode-model-option-map,
           vendor/zcode-cua
     许可证副本：licenses/zcode-APACHE-2.0.txt
     上游 commit：见 evopanel/scripts/zcode-vendor-manifest.json
     商业条款：允许商用、闭源、修改、无须付费。

2. MIT License
   - DeerFlow（bytedance/deer-flow, Copyright 2025 Bytedance Ltd. and/or
     its affiliates, 2025-2026 DeerFlow Authors）
     范围：backend 与 docs 中的 DeerFlow 衍生段（详见 NOTICE）
     许可证副本：licenses/deerflow-MIT.txt
     商业条款：允许商用、闭源、修改、无须付费。

3. Apache License 2.0（含 OFL 等子许可）
   - skills/public/canvas-design, frontend-design, skill-creator/
     （Anthropic Agent Skills 系列，详见 NOTICE "Bundled document skills
     note" 一节）

4. MIT
   - evopanel/vendor/liquid-glass-theme/（Rainpomelo/deepseek-harness-
     liquid-glass-theme）

5. MIT
   - evopanel/public/icons/ 中基于 @lobehub/icons-static-svg 的品牌图标
     （Copyright (c) LobeHub <i@lobehub.com>）

版权与商标声明：EvoFlow / EvoPanel / EvovexAI 名称为景银泰 / EvovexAI
持有的品牌名；其余品牌名归各所有人所有，仅用于产品标识。
```

> 模板可由法务在发版前按实际情况更新许可证列表与日期，作为对外尽调附件。

---

## 附录 B：版本变更

| 日期 | 变更 | 提交 |
|---|---|---|
| 2026-10-15 | 初稿：补 ZCode 归属、合规动作清单、商业化影响分析 | 见提交历史 |