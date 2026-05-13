# HANDOFF #4e · 2026-05-13 · UI Phase 2e · 管理端 · 审查回放（`/admin/cases/:id/trace`）

> **协议方向**：OrbitOS（Brain）→ 开发端（Factory · WSL Codex CLI / Claude Code CLI）
> **决策依据**：[[化工合规RAG工具#D37]] / [[化工合规RAG工具#D38]] / [[化工合规RAG工具#D44]] / [[化工合规RAG工具#D45]]
> **依赖**：HANDOFF #3 Phase 1 必须先 land —— `tokens.css` / `shell.css` / `router.js` / `api.js` / `shell.js` 契约就位才能开始。本轮**只写一页**，并行扇出第 5 个 Agent。

---

## 1. 目标路由

- 路由：`#/admin/cases/:id/trace`
- 仅管理员可见。`localStorage.getItem("role") !== "admin"` 时立即 `navigate("#/cases")`，**不渲染任何 DOM**
- 入口：① 报告页"查看证据 →"text-link（仅管理员视图）② 左侧 sidebar 切到"管理端 · 审查回放"项 + 点 Case ③ 直接粘贴 URL（鉴权挡在 mount 第一行）

---

## 2. 页模块目录（新建 3 个文件）

```
backend/app/static/pages/admin-trace/
├── index.js          ← 入口：registerRoute("#/admin/cases/:id/trace", mount)
├── admin-trace.html  ← 模板片段（fetch 后 innerHTML，或 import.meta 内联字符串）
├── admin-trace.css   ← 页面专属样式（trc-layout / trc-tl / trc-node / trc-panel / topk-row）
```

**禁止**碰 `static/pages/` 之外任何文件；禁止改 .py / 后端；禁止 nav / sidebar 重写。

---

## 3. 页面层级（参考 `docs/UI_v01/11-admin-trace.html` 的 `.frame` 内部，丢 `.caption` + 外层 `<style>` 里的 `.caption` 规则）

### 3.1 · 顶部 Case 元信息条（main 内最顶）

`parchment` 底 + 32px padding，**复用 `shell.js` 的 `setStepbar()` 或在 main 内自渲染**。内容：
- 上行 caption：`{case_no} · {scenario} · {market} · 审查日期 {YYYY-MM-DD}`
- display-md 34px：`审查回放 · {案件标题}`
- caption：`10 节点全链路 trace · 总耗时 {mm:ss} · Token 用量见详情面板`
- chip 横排：「已识别 N」「需补 N」「可查 N」「阻断 N」「结论 · {label}」(沿用 `.chip.strong` + `.dot.{pass|warn|block|mute}`)
- 右侧两个 `.cta-pearl`：「导出 trace JSON」「返回客户视图」（后者 = `navigate("#/cases/" + id)`）

### 3.2 · 主体 `.trc-layout`（左右两栏 grid）

- **左栏 320px** `.trc-tl`（pearl 底 + 右 hairline）：10 节点垂直时间线
  - 节点顺序：加载任务 / 解析 SDS / 解析配方 / 解析工艺 / RAG 召回 / Rerank / Agent 分支 / 主审 / 交叉质检 / 生成报告
  - 每节点：`.dot.{pass|warn|block|mute}`（当前节点 + `running` 状态用 `.spinner` 通用类）+ 节点名 + caption 耗时
  - 点击节点 → 切右栏 + 节点容器加 `.active`
- **右栏弹性** `.trc-detail`：选中节点详情
  - display-md 34px ttl：`{节点名} · 节点详情`
  - sub caption 行：耗时 / 查询数 / TopK 参数 / 命中 / Token 用量（按节点字段不同）
  - **4 个 `<details class="trc-panel">` 折叠面板**（默认全部折叠，点击展开）：
    1. 查询构造（query 列表 `<pre>`）
    2. TopK · 命中 chunks（`.topk-row` 表）
    3. 输入 / 输出 schema（JSON 折叠态显文字摘要"折叠中 · 共 X KB JSON"）
    4. Agent 分支推理链（3 路并行摘要）

---

## 4. API 契约

- `await api.cases.get(id)` → 拿 Case 元信息（编号 / 标题 / 场景 / 市场 / 审查日期 / chip 统计）
- `await api.cases.retrievalPreview(id)` → 拿 trace 数据（10 节点 + 每节点 detail payload）
- 如需评测元数据：`await api.evaluation.chemical()`

**trace JSON schema 来源**：去 `backend/app/chemical_rag.py:run_trace`（或同等函数）读返回结构，**只读不改 .py**；按返回的字段映射进 4 个折叠面板。字段缺失时面板 body 显 `折叠中 · 暂无数据`，**不要造数据**、**不要抛异常**。

---

## 5. 状态色与动效

- 节点点 = `.dot` + `.dot.pass/.warn/.block/.mute`（Phase 1 在 `shell.css` 已暴露通用类）
- 当前进行中节点（如果实时回放）= `.dot` 外圈加 `.spinner` 通用类
- **禁止用 emoji 图标**（D44 Anti-vision）；状态色只表态，不引导操作
- 折叠面板用原生 `<details>` + `summary::-webkit-details-marker{display:none}`，箭头自行 CSS 实现

---

## 6. Anti-vision

- ❌ 不碰 `static/pages/` 之外任何文件（含 nav / sidebar / shell.js / 其他 page）
- ❌ 不碰 `.py` / 后端 / 任何 API endpoint
- ❌ 不引入框架 / 打包器 / 任何 npm 依赖
- ❌ 不把这页字段塞进客户报告页或 PDF —— 这页只给徐钰 / 彭祎来排错用
- ❌ 不做"实时 SSE 回放"动画 —— 静态渲染既有 trace 数据即可；如 `running` 状态存在则加 spinner，不主动 poll

---

## 7. 验收

- [ ] `localStorage.setItem("role","admin")` 后访问 `#/admin/cases/{某真实 id}/trace`：顶部元信息条 + 左栏 10 节点 + 右栏默认节点详情同时渲染
- [ ] 点左栏任意节点 → 右栏 ttl / sub / 4 折叠面板内容切换，节点容器加 `.active` 高亮
- [ ] 点折叠面板 summary → 展开/收起；初始全部折叠
- [ ] `localStorage.setItem("role","client")` 后访问该路由 → 立即跳 `#/cases`，**不闪烁渲染**
- [ ] 控制台无 error / 无 404 / 无 unhandled promise rejection
- [ ] 浏览器目测：版式贴合 `docs/UI_v01/11-admin-trace.html`（去掉 `.caption` 标注帧），左 320 / 右弹性 / ttl 34px

---

## 8. 回传

### 8.1 · `IMPLEMENTATION_LOG.md` 顶部追加

```markdown
## 任务 #3e · 2026-05-13 HH:MM · UI Phase 2e Admin 审查回放

**完成 / Done**
- 新建 admin-trace/index.js + .html + .css
- 接 api.cases.get + retrievalPreview
- 路由级管理员鉴权 + 非管理员重定向

**决策 / Decisions**
- trace 字段映射策略（哪些走面板 1 / 2 / 3 / 4，缺失字段怎么兜底）

**阻塞 / Blockers**：无 / 或具体描述（如 retrievalPreview schema 与设计稿字段对不上）

**下一步 / Next**：等 Phase 2 所有 6 个 Agent 都 land 后做集成验收
```

### 8.2 · 如踩坑，`NEW_TRAPS.md` 顶部追加

特别注意：① `<details>` 默认 marker 在不同浏览器的清除写法 ② `localStorage` 在路由首次 mount 时的读取时序 ③ retrievalPreview 返回大 JSON 时面板 body 的渲染性能（>50KB 时考虑懒渲染）

---

## 9. 边界

- 不要 git commit / push / 建分支
- HANDOFF 内自相矛盾 → 写 Blocker 停手等用户
- 不要访问 Windows `E:/AI/Mulit-agents/`

---

**OrbitOS 签名**：徐钰 / OrbitOS Agent · 2026-05-13 · 决策依据 [[化工合规RAG工具#D45]]
