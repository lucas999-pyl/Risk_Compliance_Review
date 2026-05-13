# HANDOFF #4c · 2026-05-13 · UI Phase 2c：报告页 3 态（`#/cases/:id`）

> **协议方向**：OrbitOS（Brain）→ 开发端（Factory · WSL Codex CLI / Claude Code CLI）
> **依赖契约**：HANDOFF #3 已落地（tokens.css / shell.css / router.js / shell.js / api.js / `/static/pages/` 目录已开放）
> **决策依据**：[[化工合规RAG工具#D37]] 不合规四件套口径 · [[化工合规RAG工具#D45]] Phase 2 并行扇出
> **设计稿**：`docs/UI_v01/07-report-default.html` / `08-report-drawer.html` / `09-report-rerun.html`（**只取 `.frame` 内部，丢 `.caption`**）+ Spec §6.3

---

## 1 · 目标路由

`#/cases/:id` —— 已完成 Case 的家，永久默认视图。进入时先 `await api.cases.get(id)`，根据返回 `phase` / `latest_verdict` / `range_dirty` 决定渲染哪种态：

| 态 | 设计稿 | 判定条件 |
|---|---|---|
| **默认态** | 07 | Case 已完成 Step 5，`range_dirty` 为 false |
| **抽屉态** | 08 | 默认态基础上点击右上 icon → 抽屉从右侧滑入 400px（CSS transform 即可，不做物理移除） |
| **待重跑态** | 09 | `range_dirty` 为 true（用户从外部修改了 Step 4 审查范围） |

抽屉态本质上是默认态加 `body.drawer-open` class；不要再独立路由化。

---

## 2 · 文件目录

```
backend/app/static/pages/report/
├── index.js      # registerRoute("#/cases/:id", mount) 入口
├── report.html   # 3 态共用模板（default / drawer / rerun 通过 hidden class 切换）
└── report.css    # page-specific 样式
```

入口模块由 shell.js 在路由命中时 dynamic `import()`，不要在 `index.html` 预加载。

---

## 3 · 核心组件 · 主结论卡（hero-card）

- **页面唯一带 shadow 的元素**：`box-shadow: rgba(0,0,0,0.22) 3px 5px 30px`
- 结构：色点 tag → `<h2>` verdict（display-md 34/600 中文，"需复核"/"可审"/"不可审"/"待补件"）→ `.lead`（28/300 一句话总结）→ `.foot`（仅管理员可见：审查日期 / 规则库版本）
- 80px 内边距，占满内容宽（左右 margin 48px）
- **mute 变体**（待重跑态）：`background: parchment` + `box-shadow: none` + `border: 1px dashed hairline`，`h2` 与 `.lead` 颜色降到 mute / ink-48

---

## 4 · 核心组件 · 不合规四件套清单（严格按 D37）

每条一张 light tile，**相邻 tile 颜色交替**：`tile-white` ↔ `tile-parchment`。每条结构（设计稿 07 第 297-375 行）：

```
[编号 num 48/600]                              [严重度 chip · status 色]
违反规则  规则编号（rule-id 14/600） + 规则原文（blockquote 15/400）
用户原文  上传资料里相关那段原文（blockquote）
改进建议  一句到三句具体改进意见（body 16/400）
                                               [查看证据 →]（仅管理员可见）
```

数据契约（从 `api.cases.get(id)` 返回的 `findings[]` 取）：每条 `{ no, rule_id, rule_text, user_quote, suggestion, severity: "block"|"warn", evidence_ref }`。

**待重跑态**：整个 `.findings` 容器加 `opacity:.45; filter:saturate(0.4)`，标题颜色降到 `#bbb`（设计稿 09 第 303-304 行）。

---

## 5 · 管理员视角联动

启动时读 `localStorage.getItem("role") === "admin"`，给 `<main>` 加 `role-admin` class，CSS 控制可见性：

1. **主结论卡 `.foot`**：仅 `.role-admin` 可见（审查日期 + 规则库版本 + 主审）
2. **每条不合规 `.evi` 链接**："查看证据 →"：仅 `.role-admin` 可见；点击 → 触发 `openDrawer({ tab: 'rag-evidence', findingNo: 01 })`
3. **抽屉 tabs**：客户态只有 1 个 tab（时间线）；admin 态多 3 个 `admin-only` tabs（RAG 证据 / Agent 分支 / 规则匹配），CSS 用 `:not(.role-admin) .admin-only { display:none }` 控制

订阅 `window.shell` 的角色切换事件（若 shell.js 提供）；否则监听 storage 事件兜底。**禁止把"查看证据"暴露给客户视角**。

---

## 6 · PDF 下载按钮

状态条右侧 Pill 按钮"下载 PDF"：

```js
btn.addEventListener("click", () => {
  btn.disabled = true;
  btn.textContent = "正在生成报告…";
  window.open(`/api/cases/${id}/report.pdf`, "_blank");
  setTimeout(() => { btn.disabled = false; btn.textContent = "下载 PDF"; }, 3000);
});
```

**不直接调 PDF API**，浏览器原生 `window.open` 即可触发后端生成与下载。后端实现由 4f Agent 负责，本 Agent 只调路由——即使后端未实施，至少触发请求并见 loading 态。

---

## 7 · API & 抽屉时间线

- `api.cases.get(id)` 拿全部数据（phase / verdict / lead / findings / timeline / range_dirty）
- 抽屉时间线 5 个节点（Step 1-5）+ 1 个签发节点，结构见设计稿 08 第 391-396 行
- 点击时间线节点 → 暂不跳转（V1 占位），只切换节点高亮态
- 待重跑态："重新运行预审" Pill 按钮：`navigate("#/cases/:id/new?step=5")` 跳回 Wizard Step 5

---

## 8 · Anti-vision

- ❌ 不碰 `static/pages/report/` 之外的任何文件
- ❌ 不碰 `.py` / 后端 / `factory.py`
- ❌ 不给除 `.hero-card`（非 mute 态）之外的任何元素加 box-shadow
- ❌ 不把"查看证据 →"暴露给客户视角
- ❌ 状态色（pass/warn/block/mute）只用作 chip 与少量小字，**禁止当 CTA 色 / 大面积背景填充**
- ❌ 不引入框架 / 打包器 / 第三方 UI 库——原生 JS + ES Modules
- ❌ 不主动改 `_build/core.css` / `docs/UI_v01/` 设计稿原件
- ❌ 不复制 `.caption` 标注帧到 `report.html`

---

## 9 · 验收

- [ ] `#/cases/:id` 三种态视觉与 07/08/09 设计稿 `.frame` 内部一致（边到边交替 tile / 主结论卡 shadow / 待重跑灰化）
- [ ] `localStorage.setItem("role","admin")` 刷新后：主结论卡 foot 可见 / 每条"查看证据 →"出现 / 抽屉多 3 个 admin tabs；切回 `client` 全部消失
- [ ] "下载 PDF"按钮点击触发浏览器请求 `/api/cases/:id/report.pdf`（后端 404 也算通过本轮验收）；按钮短暂进入 loading 态
- [ ] 抽屉打开 / 关闭过渡平滑（CSS transform 300ms）
- [ ] 控制台无 error / 无 404（除 PDF API 外）

---

## 10 · 回传

### 10.1 · `IMPLEMENTATION_LOG.md` 顶部追加

```markdown
## 任务 #3c · 2026-05-13 HH:MM · UI Phase 2c 报告 3 态

**完成 / Done**
- pages/report/{index.js, report.html, report.css}
- 3 态切换（default / drawer / rerun）已串通 api.cases.get
- localStorage role 切换联动管理员可见元素
- PDF 下载按钮触发 window.open

**决策 / Decisions**
- 抽屉态用 body class 切换而非独立路由，理由是 ...
- role 切换用 CSS class + localStorage，不引入状态管理库

**阻塞 / Blockers**：无 / 或具体描述

**下一步 / Next**：等 4f Agent 完成 PDF 后端
```

### 10.2 · 如踩坑写 `NEW_TRAPS.md` 顶部

特别关注：① 抽屉 transform 在 `.frame` grid 上下文里的 stacking context ② role 切换后 `.admin-only` 元素的渐入是否有 FOUC

---

## 11 · 边界

- 不要 git commit / push / 建分支
- 不要动 `.env`
- 不要访问 Windows `E:/AI/Mulit-agents/`
- HANDOFF 范围内有自相矛盾 → 写 Blocker 停手等用户

---

**OrbitOS 签名**：徐钰 / OrbitOS Agent · 2026-05-13 · 决策依据 [[化工合规RAG工具#D37]] / [[化工合规RAG工具#D45]]
