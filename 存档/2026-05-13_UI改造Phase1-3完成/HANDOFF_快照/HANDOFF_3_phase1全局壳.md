# HANDOFF #3 · 2026-05-13 · UI 改造 Phase 1（串行根）：全局壳 + 设计 token + 路由 + 静态资源挂载

> **协议方向**：OrbitOS（Brain）→ 开发端（Factory · WSL Codex CLI / Claude Code CLI）
> **OrbitOS 决策依据**：[[化工合规RAG工具#D37]] / [[化工合规RAG工具#D38]] / [[化工合规RAG工具#D44]] / [[化工合规RAG工具#D45]]
> **覆盖说明**：上一轮 HANDOFF #1.2 已完成（task #1，79 tests pass）。本 HANDOFF 是 UI 改造分三阶段（D45）的 **Phase 1 串行根**——Phase 2 的 6 个并行 Agent 都依赖本轮产出的契约，必须先跑完本轮再开 Phase 2。

---

## 1. 上下文（最少必读）

- **设计稿**：`docs/UI_v01/` 已有 15 张 HTML 视觉稿 + `index.html` 索引 + `_build/core.css`（共享 token） + `_build/helpers.js`
- **设计 spec**：`docs/UI_v01/uploads/UI_RedesignSpec_2026-05-13.md`（17 节，本 HANDOFF 的对齐源）
- **风格基底**：`docs/UI_v01/uploads/DESIGN.md`（Apple 美学完整 token 表）

**所有设计稿的 `.caption` 是 Claude Design 标注帧**，移植时**只取 `.frame` 内部**，丢掉 `.caption`、外层 `<style>` 里的 `.caption` 规则、屏外 banner 等。

---

## 2. 本轮任务 4 个原子动作

| # | 动作 | 必须 / 可选 |
|---|---|---|
| T1 | 抽取设计 token 到 `static/css/tokens.css` | 必须 |
| T2 | 全局壳静态资源（4 个新 .css/.js 文件 + 新 `index.html` + `legacy.html` 兜底） | 必须 |
| T3 | 后端 `factory.py` 挂 `StaticFiles` 路由 + 加 `/legacy` 路由 | 必须 |
| T4 | smoke 验收（pytest + uvicorn + curl + 浏览器目测） | 必须 |

---

## 3. T1 · 抽取设计 token（`static/css/tokens.css`）

来源：`docs/UI_v01/_build/core.css` 的 `:root{...}` 段 + `docs/UI_v01/15-token-summary.html` 的 token 速查面板（如果两者冲突，以 `_build/core.css` 为准——15-token-summary 是给徐钰看的可视化文档，不是源真）。

**最终 `tokens.css` 包含**：
- 颜色：`--primary` / `--ink` 全套灰阶 / `--canvas` / `--parchment` / `--pearl` / `--tile-dark` / 4 个 status 色（pass/warn/block/mute） / hairline / divider-soft
- 字体：`--font-display` / `--font-text`（中文化适配 `"PingFang SC", "SF Pro Display", ...`）
- 不要把字号 / 圆角 / 间距塞进 token——这些每个组件用得姿势不一样，留给各页 CSS 自己写

---

## 4. T2 · 全局壳静态资源

### 4.1 · 文件清单（新建 8 个，重命名 1 个）

```
backend/app/static/
├── index.html              ← 新建：壳 HTML（替换原 99607 字节大单文件）
├── legacy.html             ← 重命名自原 index.html（兜底，路由 /legacy 可访问）
├── css/
│   ├── tokens.css          ← T1 抽取
│   └── shell.css           ← 全局壳样式（nav / sidebar / progress bar）
├── js/
│   ├── router.js           ← Hash router（#/cases、#/cases/:id、#/cases/:id/new、#/admin/kb、#/admin/cases/:id/trace）
│   ├── api.js              ← 后端 API 客户端封装（GET/POST/DELETE 统一 fetch，含错误兜底 + 演示知识包自动检测）
│   ├── shell.js            ← 全局壳 mount（nav 状态、sidebar Case 列表、视角切换器、路由变更回调）
│   └── pages/.gitkeep      ← 空目录，Phase 2 各 Agent 在此创建自己的子目录
└── pages/                  ← 空目录，由 Phase 2 各 Agent 填充
    └── .gitkeep
```

### 4.2 · `index.html`（新壳）骨架（核心要求）

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>化工合规 RAG 预审</title>
  <link rel="stylesheet" href="/static/css/tokens.css">
  <link rel="stylesheet" href="/static/css/shell.css">
</head>
<body>
  <div class="frame">
    <header class="gnav" id="shell-nav"><!-- shell.js 注入 nav 内部 --></header>
    <div class="pbar" id="shell-pbar"><!-- 顶部 2px 进度条 4 段 --></div>
    <div class="stepbar" id="shell-stepbar"><!-- 当前步骤文案 --></div>
    <aside class="side" id="shell-side"><!-- Case 列表 --></aside>
    <main class="main" id="route-outlet"><!-- 路由 mount 点；Phase 2 各页模块挂这里 --></main>
  </div>
  <script type="module" src="/static/js/shell.js"></script>
</body>
</html>
```

`.frame` 用 CSS grid（参考 `docs/UI_v01/_build/core.css` 第 19 行 `grid-template-areas`）。

### 4.3 · `router.js` 契约（**Phase 2 Agent 写自己的页必须遵守**）

```javascript
// router.js 导出
export function registerRoute(pattern, mountFn);
// pattern: "#/cases" / "#/cases/:id" / "#/cases/:id/new" / "#/admin/kb" / "#/admin/cases/:id/trace"
// mountFn: async (outlet, params) => { ... }
//   - outlet: DOM element（即 #route-outlet）
//   - params: { id?, step? } 路由参数 + query string
//   - mountFn 内可改 outlet.innerHTML，可加 listener；返回值忽略
// 同一时间只有一个路由活动；路由切换时 outlet.innerHTML = ""（旧 mount 自动卸载）

export function navigate(hash);  // 程序化跳转
export function getCurrentRoute();
```

**Phase 2 各 Agent 的页模块约定**：导出 `mount(outlet, params)`，由各自的入口模块 `pages/<X>/index.js` 调用 `registerRoute("#/...", mount)`。每页的入口模块在 `index.html` 的 `<head>` 里**不要预加载**——shell.js 按需 dynamic import。

### 4.4 · `shell.js` 职责

- 启动时挂载 nav / sidebar 静态结构
- 监听 hashchange，决定动态 `import("/static/pages/<page>/index.js")`，调用 router 派发
- 暴露 `window.shell.setProgress(step, total, subtasks)` 让 Wizard 用
- 暴露 `window.shell.setStepbar(text, tasksHTML)` 让各页用
- 视角切换器（客户预审 / 管理端）只是个 UI 开关——管理员视角解锁 `#/admin/*` 路由 + 报告页右侧抽屉的 admin tabs；本轮不做后端鉴权（V1 演示用），只在 client localStorage 存 `role=admin|client`

### 4.5 · `api.js` 契约

封装现有所有后端 endpoint（已存在的，从 `factory.py` 抓出来的）：

```javascript
export const api = {
  cases: {
    list, create, get, delete: del, uploadDocuments, runReview,
    retrievalPreview, queryPresets,
  },
  knowledge: {
    status, chunks, search, importDemoPack, uploadPack, clear,
  },
  technology: { runs, evaluation },
  evaluation: { chemical: () => fetch("/chemical/evaluation") },
  // 重要：内部自动检测 knowledge.status() → 若 chunk_count === 0 → 在 runCaseReview 前
  // 自动 importDemoPack() 兜底，避免老 UI 的"知识库未加载"静默闸门（详见 IMPLEMENTATION_LOG #1 现场补充）
};
```

不要重复实现新的 endpoint——本轮纯客户端工作。

### 4.6 · `shell.css`

只放全局壳样式（gnav / side / pbar / stepbar / main + cta-primary / cta-ghost / chip / dot 通用工具类）。**page-specific 样式留给 Phase 2 各 Agent 自己写**。

从 `docs/UI_v01/_build/core.css` 抽取，但**去掉 `.caption` 段** 与 `.wzbody / .uplist / .mc-grid / .scope-row / .runcard` 等 page-specific 段（那些归 Wizard Agent）。

---

## 5. T3 · 后端 `factory.py` 改 2 处

### 5.1 · 挂 StaticFiles（必须，否则 `/static/css/...` / `/static/pages/...` 404）

```python
from fastapi.staticfiles import StaticFiles

app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
```

放在 `app.add_middleware(CORSMiddleware, ...)` 之后、第一个 `@app.get("/health")` 之前。

### 5.2 · `/legacy` 路由（兜底）

```python
@app.get("/legacy", include_in_schema=False)
def legacy() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "legacy.html", media_type="text/html; charset=utf-8")
```

原 `@app.get("/")` 路由不变（仍指 `static/index.html`），只是 `index.html` 内容由本 HANDOFF 改写。

### 5.3 · 不要动的

- `/health`、所有 `/chemical/*` API、所有业务路由 — **一律不碰**
- `chemical_rag.py` / `service.py` / `store.py` / `vector_store.py` / `models.py` / `settings.py` / `ai_clients.py` — **一律不碰**

---

## 6. T4 · 验收 smoke

- [ ] `python -m compileall backend/app` exit 0
- [ ] `python -m pytest` 79 tests 全过（**不要为了 pass 删测试或加 skip**）
- [ ] `uvicorn app.main:app --app-dir backend --reload --port 8888` 起服务无 import error
- [ ] `curl -s http://127.0.0.1:8888/health` → `{"status":"ok"}`
- [ ] `curl -sI http://127.0.0.1:8888/static/css/tokens.css` → 200
- [ ] `curl -sI http://127.0.0.1:8888/static/js/router.js` → 200
- [ ] `curl -sI http://127.0.0.1:8888/legacy` → 200
- [ ] `curl -s http://127.0.0.1:8888/` → 返回新壳 HTML（含 `<div class="frame">` 与 `<main id="route-outlet">`）
- [ ] 浏览器目测：打开 `http://127.0.0.1:8888/`，看到顶部黑色 nav（44px 高）+ 左侧 240px 灰底 sidebar + 主区空白（route-outlet 等待 Phase 2 填充）；切到 `http://127.0.0.1:8888/legacy` 看到老 UI 完整可用

---

## 7. Anti-vision（**严格遵守**）

- ❌ 不要替 Phase 2 的页面实现任何东西 — Phase 2 的 6 个 Agent 各自有 HANDOFF #4a-#4f，本轮**只搭骨**
- ❌ 不要引入 React / Vue / Svelte / 任何框架 / 任何打包器（webpack/vite/esbuild） — 沿用原生 JS + ES Modules + FastAPI StaticFiles
- ❌ 不要动 `chemical_rag.py` / 业务后端 — 本轮纯前端 + factory.py 加 2 行 StaticFiles 与 1 个 `/legacy` 路由
- ❌ 不要写测试 — 本轮纯静态资源 + 浏览器层契约，pytest 套件已覆盖业务逻辑
- ❌ 不要主动改 `_build/core.css` / `docs/UI_v01/` 任何文件 — 那是设计稿原件，read-only 参考
- ❌ 不要在新 `index.html` 里塞业务逻辑 — 业务都在 Phase 2 的 page modules 里

---

## 8. 完成后回传

### 8.1 · `IMPLEMENTATION_LOG.md` 顶部追加

```markdown
## 任务 #2 · 2026-05-13 HH:MM · UI Phase 1 全局壳 + 设计 token + 路由 + StaticFiles

**完成 / Done**
- T1: tokens.css N 行抽取
- T2: 新建 8 文件 + 重命名 1 文件清单
- T3: factory.py StaticFiles 挂载 + /legacy 路由
- T4: smoke 全项 pass

**决策 / Decisions**
- 选了 ES Modules 而非 IIFE / global 模式，理由是 ...
- router 用 hashchange 而非 history API，理由是 ...（避免 FastAPI 路由 catch-all 改造）

**阻塞 / Blockers**：无 / 或具体描述

**下一步 / Next**
- 等用户分发 HANDOFF #4a-#4f 到 6 个并行 Agent，按 router.js 契约填充 pages/<X>/
```

### 8.2 · 如踩坑，`NEW_TRAPS.md` 顶部追加

特别注意 pydantic / FastAPI 与 StaticFiles 的潜在交互；以及 ES Modules 在 FastAPI 默认 MIME 配置下的 Content-Type 是否正确（应是 `application/javascript`）。

---

## 9. 边界

- 不要 git commit / push / 建分支
- 不要动 `.env` 本体（用户已手填实 Key）
- 不要访问 Windows `E:/AI/Mulit-agents/`
- HANDOFF 范围内有自相矛盾 → 写 Blocker 停手等用户

---

**OrbitOS 签名**：徐钰 / OrbitOS Agent · 2026-05-13 · 决策依据 [[化工合规RAG工具#D45]]
