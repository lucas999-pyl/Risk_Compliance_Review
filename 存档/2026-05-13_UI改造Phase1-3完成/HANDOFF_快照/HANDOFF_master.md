# HANDOFF #4-master · 2026-05-13 · UI 改造 · 串行根 → 并行扇出 → 串行收尾

> **协议方向**：OrbitOS（Brain）→ 开发端（Factory · WSL Claude Code CLI / Codex CLI）
> **OrbitOS 决策依据**：[[化工合规RAG工具#D37]] / [[化工合规RAG工具#D38]] / [[化工合规RAG工具#D44]] / [[化工合规RAG工具#D45]]
> **覆盖说明**：上一轮 HANDOFF #1.2 已完成（task #1，79 tests pass，dev server PID 15735）。本轮 UI 改造采用"主 Agent 自己内置 sub-Agent 并行"模式，**不要让用户开多终端**。

---

## 1. 执行架构（**强制遵守**）

```
你（主 Agent）
├── Phase 1（串行根 · 你自己干）
│     └── 完整执行 docs/UI_v01/handoffs/HANDOFF_3.md
│         产出 tokens.css / shell.css / router.js / api.js / shell.js / 新 index.html / legacy.html / factory.py 改 2 处
│         所有 Phase 2 Agent 的契约依赖都来自这里
│
├── Phase 2（并行扇出 · 单条消息内 spawn 6 个 sub-Agent）
│     用你的 Task / Agent 工具，在**单条消息**里同时派发 6 个 sub-Agent：
│     ├── sub-Agent A → docs/UI_v01/handoffs/HANDOFF_4a.md（Case 看板 · static/pages/case-board/）
│     ├── sub-Agent B → docs/UI_v01/handoffs/HANDOFF_4b.md（Wizard 5 步 · static/pages/wizard/）
│     ├── sub-Agent C → docs/UI_v01/handoffs/HANDOFF_4c.md（报告 3 态 · static/pages/report/）
│     ├── sub-Agent D → docs/UI_v01/handoffs/HANDOFF_4d.md（Admin 知识库 · static/pages/admin-kb/）
│     ├── sub-Agent E → docs/UI_v01/handoffs/HANDOFF_4e.md（Admin 审查回放 · static/pages/admin-trace/）
│     └── sub-Agent F → docs/UI_v01/handoffs/HANDOFF_4f.md（PDF 后端 Playwright · pdf_render.py + static/print/ + factory.py 加 2 路由）
│     每个 sub-Agent 工作目录互不重叠，文件域无冲突（详见 §3 文件域审计）
│
└── Phase 3（串行收尾 · 你自己干）
      6 个 sub-Agent 全部回报后：
      ├── 把它们各自的 LOG 段（四段式）按顺序合并写入 IMPLEMENTATION_LOG.md（任务 #3a → #3f）
      ├── 把它们各自的 NEW_TRAPS 段（如有）合并写入 NEW_TRAPS.md
      ├── 跑集成 smoke：pytest 全过 / uvicorn 起服务 / 浏览器 7 条路由全部目测
      └── 最后写一条 ## 任务 #4 · UI 改造全收完 · 集成 smoke 到 LOG 顶部
```

---

## 2. Step-by-Step

### Step 1 · Phase 1 串行根（你自己干）

1. Read `docs/UI_v01/handoffs/HANDOFF_3.md` 完整正文（这是原 Phase 1 详情 HANDOFF #3）
2. 按它的 4 个原子任务（T1 抽 token / T2 写 8 个新文件 + 重命名 1 个 / T3 factory.py 加 StaticFiles + /legacy 路由 / T4 smoke）执行
3. 完成后追加 `## 任务 #2 · UI Phase 1 全局壳 + 设计 token + 路由 + StaticFiles` 四段式到 IMPLEMENTATION_LOG.md
4. 验收 pass 才进 Step 2；不 pass 写 Blocker 停手

### Step 2 · Phase 2 并行扇出（你 spawn 6 sub-Agent）

**在单条消息内同时派发 6 个 sub-Agent**，每个 sub-Agent 的 prompt 用以下模板（**只换 X 字段**）：

```
你是化工合规 RAG 项目 UI 改造的 Phase 2 sub-Agent {X}。

工作目录：/home/oneus/projects/化工合规工具/Risk_Compliance_Review/
任务书：完整 Read docs/UI_v01/handoffs/HANDOFF_4{X}.md，严格按它的全部 § 执行。

文件域（**只能动这个目录或这些文件，越界=违规**）：
{X=a: backend/app/static/pages/case-board/}
{X=b: backend/app/static/pages/wizard/}
{X=c: backend/app/static/pages/report/}
{X=d: backend/app/static/pages/admin-kb/}
{X=e: backend/app/static/pages/admin-trace/}
{X=f: backend/app/pdf_render.py（新建）+ backend/app/static/print/（新建目录）+ backend/app/factory.py（加 2 路由，不动既有逻辑）}

全局约束：
- 不要 git commit/push/建分支
- 不要打开 .env 本体；不要访问 Windows /AI/Mulit-agents/
- 不要碰其他 sub-Agent 的文件域；不要碰业务后端（chemical_rag / service / store / vector_store / settings / ai_clients）
- 不引入 React/Vue/Svelte/任何框架/任何打包器
- 设计稿 .caption 必丢弃，只移植 .frame 内部

完成后**不要直接写 IMPLEMENTATION_LOG.md**（避免 6 个 sub-Agent 并发写同一文件）；
把你的四段式（Done / Decisions / Blockers / Next）作为**返回结果文本**给我，我（主 Agent）统一汇总写入。
NEW_TRAPS 同理：如踩坑，把 ## TRAP #N 四段式作为返回结果的第二段给我。

验收：按任务书 §验收 跑 smoke + 浏览器目测（具体路由见任务书）。
开干。
```

**关键并行纪律**：
- ⏱️ 用你的 Task / Agent 工具一次性 spawn 全部 6 个，**不要顺序 spawn**（顺序 spawn 等于串行）
- 📁 6 个 sub-Agent 文件域已审计过互不重叠（详见 §3），可以放心并行
- 📝 sub-Agent 不写 LOG / TRAPS 文件本体（避免并发写文件冲突），把内容作为 return text 给你，你汇总后串行写

### Step 3 · Phase 3 串行收尾（你自己干）

6 个 sub-Agent 全部完成后：

1. **汇总写 LOG**：按 #3a → #3b → #3c → #3d → #3e → #3f 顺序，依次把 6 个 sub-Agent 返回的四段式追加到 `IMPLEMENTATION_LOG.md` 顶部。**注意 IMPLEMENTATION_LOG 是倒序文件**——最新在最上，所以你要先写 #3a，然后在 #3a 上方写 #3b，以此类推（让 #3f 在最顶）
2. **汇总写 TRAPS**：如有踩坑，按 sub-Agent 返回的 TRAP 内容追加到 `NEW_TRAPS.md` 顶部
3. **集成 smoke**（重要）：
   - `python -m compileall backend/app` exit 0
   - `python -m pytest` 79 tests 全过（**不要为了 pass 删测试或加 skip**）
   - 重启 `uvicorn`（必须，因为 Phase 1 加了 StaticFiles + 4f 加了 PDF 路由）
   - `curl -s http://127.0.0.1:8888/health` → `{"status":"ok"}`
   - 浏览器 7 条路由全部目测（见 §4 表）
4. 写 **最终一条** `## 任务 #4 · UI 改造全收完 · 集成 smoke` 到 LOG 顶部，四段式概要 + 列出 7 条目测路由的渲染结果

---

## 3. 文件域审计（确认 6 个 sub-Agent 不冲突）

| Sub-Agent | 写入文件 / 目录 | 与其他冲突？ |
|---|---|---|
| A (4a) | `backend/app/static/pages/case-board/*` | 否 |
| B (4b) | `backend/app/static/pages/wizard/*` | 否 |
| C (4c) | `backend/app/static/pages/report/*` | 否 |
| D (4d) | `backend/app/static/pages/admin-kb/*` | 否 |
| E (4e) | `backend/app/static/pages/admin-trace/*` | 否 |
| F (4f) | `backend/app/pdf_render.py` + `backend/app/static/print/*` + `backend/app/factory.py`（追加 2 路由） | 否（factory.py 在 Phase 1 已被 Step 1 修改完毕，4f 是追加新路由，与 Phase 1 改的位置错开） |

**唯一可能的争用点**：`factory.py` 在 Phase 1 + Phase 2-F 都会被改。但 Phase 1 在 Step 1 已经收尾才进入 Step 2，所以不存在并行写。Step 2 阶段只有 4f 一个 Agent 动 factory.py，单点写无冲突。

`IMPLEMENTATION_LOG.md` / `NEW_TRAPS.md` 由你（主 Agent）在 Step 3 串行写入，sub-Agent 不直接写——避免并发写文件冲突。

---

## 4. 集成 smoke 路由表（Step 3 用）

| 路由 | 期望 |
|---|---|
| `http://127.0.0.1:8888/` | 新壳：黑 nav + 左 sidebar Case 列表 + 主区按路由渲染 |
| `http://127.0.0.1:8888/legacy` | 老 UI 完整可用（兜底） |
| `#/cases` | Case 看板（4a） |
| `#/cases/new?step=1` ~ `?step=5` | Wizard 5 屏（4b） |
| `#/cases/<existing-id>` | 报告 3 态（4c）—— 切 localStorage role 测客户/管理员视角 |
| `#/admin/kb` | Admin 知识库（4d） |
| `#/admin/cases/<id>/trace` | Admin 审查回放（4e） |
| `curl -sI /api/cases/<id>/report.pdf` | 200 + application/pdf（4f） |

---

## 5. 全局 Anti-vision（贯穿 3 个 Phase）

- ❌ 不要 git commit / push / 建分支
- ❌ 不要打开 / 修改 `.env` 本体
- ❌ 不要访问 Windows `E:/AI/Mulit-agents/`
- ❌ 不要碰业务逻辑代码：`chemical_rag.py` / `service.py` / `store.py` / `vector_store.py` / `knowledge.py` / `models.py` / `settings.py` / `ai_clients.py`
- ❌ 不要引入 React/Vue/Svelte/框架/打包器
- ❌ 不要让 sub-Agent 顺序 spawn——必须单条消息内同时派发 6 个，否则 = 串行
- ❌ 不要让 sub-Agent 直接写 LOG / TRAPS 文件——由你（主 Agent）汇总写

---

## 6. 中断恢复

如果你（主 Agent）context 即将填满：

- **在 Step 1 中**：完成 Phase 1，写 LOG #2 收尾，停手等用户重启
- **在 Step 2 sub-Agent 跑步中**：让 sub-Agent 各自完成（它们独立 context），把它们的 return 收齐后写 LOG，再决定是否进 Step 3
- **在 Step 3 中**：写到哪步 LOG 标"⚠️ 主 Agent context 满，停在 Step 3.N"，停手

用户重启你后，你 Read LOG 看进度，从断点续跑。

---

**OrbitOS 签名**：徐钰 / OrbitOS Agent · 2026-05-13 · 决策依据 [[化工合规RAG工具#D45]]
