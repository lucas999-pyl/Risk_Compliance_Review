# HANDOFF #4a · 2026-05-13 · UI Phase 2a：Case 看板页模块（`#/cases`）

> **协议方向**：OrbitOS（Brain）→ 开发端（Factory · WSL Codex CLI / Claude Code CLI）
> **依赖契约**：HANDOFF #3 §4.3 `router.js` / §4.4 `shell.js` / §4.5 `api.js` 已落地；本轮**只在 `static/pages/case-board/` 内填充**，不动 Phase 1 全局壳
> **设计稿源**：`docs/UI_v01/01-case-board.html`（**只移植 `.frame > .main` 内的内容**，丢掉 `.caption` / `.gnav` / `.side`——后两者已由 Phase 1 `shell.js` 注入）
> **设计 spec**：`docs/UI_v01/uploads/UI_RedesignSpec_2026-05-13.md` §6.1

---

## 1. 目标

实现 `#/cases` 路由：已有 Case 时的首页 = 3 列卡片网格的 Case 看板；Case 列表为空时居中提示空态。

---

## 2. 文件清单（新建 3 个，**仅在 `static/pages/case-board/` 内**）

```
backend/app/static/pages/case-board/
├── index.js              ← mount 入口，调用 registerRoute("#/cases", mount)
├── case-board.css        ← 本页独有样式（hd / subbar / grid / card / chip / empty-card）
└── case-board.html       ← 模板片段（可由 index.js fetch 后 innerHTML 注入，或 JS 拼字符串注入；二选一，**推荐 fetch 注入**保持模板可读）
```

---

## 3. 设计稿移植规则

- **取**：设计稿 `.frame > .main` 内的 `.hd / .subbar / .grid / .card / .card.empty` 结构
- **丢**：`.caption` 整段 + `.gnav` + `.side`（已由 shell.js 全局注入）+ 设计稿 `<style>` 里 `:root{}` 段（已在 `tokens.css`）+ `.gnav / .side / .case-item` 段（已在 `shell.css`）+ body/`.frame` 段（已在 `shell.css`）
- **本页 CSS 只放**：`.hd` / `.cta-primary`（若 `shell.css` 未抽走）/ `.subbar`（含 `.seg` / `.count` / 搜索 input）/ `.grid` / `.card`（含 `.cap` / `h3` / `.meta` / `.chips` / `.chip` / `.foot` / `.status` / `.link`）/ `.card.empty`
- **不要**给卡片加 `box-shadow`（shadow 唯一保留给报告页主结论卡，见 spec §3.1）

---

## 4. API 调用契约

```javascript
import { api, navigate } from "/static/js/api.js"; // navigate 由 router.js 导出，从 api.js 转出或直接 import from "/static/js/router.js"
const cases = await api.cases.list();  // 返回 Case[] 真实数据，禁用 mock
```

**跳转规则**：
- 「新建 Case」CTA（右上 Pill 按钮） → `navigate("#/cases/new?step=1")`（不传 id，走"创建空白 Case"语义；id 由 4b Wizard Agent 创建后回填）
- 卡片右下「查看报告 →」 → `navigate("#/cases/" + c.id)`
- 卡片右下「继续 →」 / 「补件 →」 → `navigate("#/cases/" + c.id + "/new?step=" + c.next_step)`
- 整张卡片可点（cursor:pointer）→ 同上，按状态二选一

---

## 5. 卡片底部状态文案映射

按 Case 的 `latest_verdict` / `phase` / `next_step` 字段决定（字段名以后端实际返回为准，未知字段走默认）：

| 状态语义 | 状态文案（status chip） | 链接文案 | 跳转 |
|---|---|---|---|
| 已完成（verdict=pass/合规） | `pass · 可审 · 已完成` | 查看报告 → | `#/cases/:id` |
| 已完成需复核（verdict=needs_review） | `warn · 需复核 · 报告就绪` | 查看报告 → | `#/cases/:id` |
| 进行中（phase=wizard, step<5） | `mute · Step N · 当前步骤名` | 继续 → | `#/cases/:id/new?step=N` |
| 阻断缺件（verdict=blocked / 有 missing items） | `block · 缺件 · 待补资料` | 补件 → | `#/cases/:id/new?step=2` |
| 待重跑（已完成 + 范围已变） | `warn · 数据已变更` | 重新运行 → | `#/cases/:id/new?step=5` |

色点 class：`dot pass / warn / block / mute`（已在 `shell.css` 中定义，本页直接用）。

---

## 6. 空态

`cases.length === 0` 时：`.grid` 内不渲染卡片，改渲染一个居中容器（max-width 480px，文字 `display-md` 34px / 300 mute 灰）：

```
还没有 Case，从右上角"新建 Case"开始
```

「新建 Case」CTA 始终保留在 `.hd` 右侧。

---

## 7. Anti-vision（严格遵守）

- 不要碰 `static/pages/case-board/` 之外的任何文件
- 不要碰任何 `.py` / 后端路由 / 业务逻辑
- 不要碰 `static/index.html` / `static/css/tokens.css` / `static/css/shell.css` / `static/js/*.js`（Phase 1 owner 的工件）
- 不要给本页任何元素加 `box-shadow`（shadow 唯一给报告页主结论卡）
- 不要引入 React / Vue / 任何框架 / 任何打包器 — 沿用原生 ES Modules
- 不要做筛选 / 排序工具栏的真实逻辑（设计稿里的 `.subbar` 4 个 tab + 搜索框先保留视觉、不接逻辑——spec §6.1 写明 Case 数 >20 才接）
- 不要自己实现新 `/chemical/*` endpoint — 全部通过 `api.cases.list()` 拿数据

---

## 8. 验收 smoke

- [ ] `uvicorn app.main:app --app-dir backend --reload --port 8888` 启动无 error
- [ ] 浏览器开 `http://127.0.0.1:8888/#/cases`，渲染 Case 看板：顶部 hd（标题 + 副本 + 新建 CTA） + subbar（4 个 tab + 计数 + 搜索框） + 3 列卡片网格 + 末尾 dashed 新建占位
- [ ] 视觉与 `docs/UI_v01/01-case-board.html` `.frame > .main` 内部一致（卡片 18px 圆角 / hairline 边 / chip 横排 / 底部色点 + 链接）
- [ ] Case 列表数据来自 `GET /chemical/cases` 真实接口，不是 mock
- [ ] 点击「新建 Case」CTA → URL 跳到 `#/cases/new?step=1`
- [ ] 点击卡片或卡片底部链接 → URL 按 §5 表跳转
- [ ] Case 列表为空时显示 §6 空态文案
- [ ] 浏览器 DevTools console 无 error / 无 404

---

## 9. 完成后回传

### 9.1 · WSL 仓 `IMPLEMENTATION_LOG.md` 顶部追加

```markdown
## 任务 #3a · 2026-05-13 HH:MM · UI Phase 2a Case 看板

**完成 / Done**
- 新建 case-board/index.js + case-board.css + case-board.html
- registerRoute("#/cases", mount) 接入 router
- 5 种状态文案映射 + 空态实现
- 验收 smoke 全项 pass

**决策 / Decisions**
- 模板用 fetch 注入而非 JS 字符串拼接，理由：...
- subbar 4 个 tab 保留视觉骨架不接逻辑，理由：spec §6.1 Case 数 >20 才接

**阻塞 / Blockers**：无 / 或具体描述

**下一步 / Next**：等 4b-4f 并行 Agent 各自落自己的页
```

### 9.2 · 踩坑写 `NEW_TRAPS.md` 顶部（如果有）

特别注意：① 后端 Case 字段名（`latest_verdict` / `phase` / `next_step`）是否与 §5 表对得上，对不上写 Blocker 不要硬塞；② 模板 fetch 路径是 `/static/pages/case-board/case-board.html` 还是相对路径，以浏览器实测为准。

---

## 10. 边界

- 不要 git commit / push / 建分支
- 不要动 `.env`
- 不要访问 Windows `E:/AI/Mulit-agents/`
- HANDOFF 范围内有自相矛盾 → 写 Blocker 停手等用户

---

**OrbitOS 签名**：徐钰 / OrbitOS Agent · 2026-05-13 · 决策依据 [[化工合规RAG工具#D45]]
