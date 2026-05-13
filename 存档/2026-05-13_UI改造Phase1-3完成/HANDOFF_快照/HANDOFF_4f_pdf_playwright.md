# HANDOFF #4f · 2026-05-13 · UI 改造 Phase 2f：PDF 客户报告后端（Playwright 渲染 + 打印模板）

> **协议方向**：OrbitOS（Brain）→ 开发端（Factory · WSL Codex CLI / Claude Code CLI）
> **OrbitOS 决策依据**：[[化工合规RAG工具#D37]] / [[化工合规RAG工具#D44]]（⑤后端渲染 / ⑥模板结构 / ⑦不入项）
> **依赖**：HANDOFF #3（Phase 1 全局壳 + `app.mount("/static", ...)`）**必须先 merge**，否则新打印模板挂不上、`/print/...` 路由会撞静态目录。
> **本轮位置**：Phase 2 并行扇出的 6 个 Agent 之一；是**唯一触碰后端**的 Agent（4a-4e 全在 `static/pages/` 写前端）。

---

## 1 · 任务全景

你新增 **1 个后端模块 + 2 个后端路由 + 1 套打印模板**，让前端 4c 报告页用 `window.open("/api/cases/" + id + "/report.pdf")` 即可触发下载。完全不碰业务逻辑、不动 settings / ai_clients / 任何 RAG/Agent 文件。

---

## 2 · 目标产出（3 部分）

### 2.1 · 后端模块 `backend/app/pdf_render.py`（新建）

```python
async def render_case_report_pdf(case_id: str, store: SQLiteStore) -> bytes:
    """
    用 Playwright headless chromium 加载 http://127.0.0.1:<port>/print/cases/<case_id>/report，
    等待 networkidle，page.pdf(format='A4', margin={top:25mm, bottom:25mm, left:20mm, right:20mm},
    print_background=True) 返回字节流。
    """
```

- 使用 `playwright.async_api`；启动后单例 chromium，复用 browser context（避免每次冷启动 1-2s）
- 字体嵌入：用 `@font-face` 在打印模板里指向 Noto Sans CJK SC / PingFang SC 系统字体；chromium 渲染时自动嵌入子集
- 失败处理：抛 `PDFRendererUnavailable` / `CaseNotReady` 等业务异常，由路由层 catch 转 HTTP 错误码

### 2.2 · 后端 2 路由（追加到 `backend/app/factory.py`）

放在 `app.mount("/static", ...)` 之后、业务路由附近：

```python
from app.pdf_render import render_case_report_pdf, PDFRendererUnavailable, CaseNotReady

@app.get("/api/cases/{case_id}/report.pdf", include_in_schema=False)
async def case_report_pdf(case_id: str) -> Response:
    case = store.get_case(case_id)
    if not case: raise HTTPException(404, "Case not found")
    latest = store.latest_report(case_id)
    if not latest:
        return JSONResponse({"error": "Case has no completed review yet"}, status_code=409)
    try:
        pdf_bytes = await render_case_report_pdf(case_id, store)
    except PDFRendererUnavailable:
        return JSONResponse({"error": "PDF renderer not available",
                             "hint": "运行 playwright install chromium"}, status_code=500)
    today = datetime.now().strftime("%Y%m%d")
    filename = f"{case_id}_审查报告_{today}.pdf"
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})

@app.get("/print/cases/{case_id}/report", include_in_schema=False)
def case_report_print_template(case_id: str) -> HTMLResponse:
    """打印态 HTML。chromium 内部访问转 PDF；也允许人工打开调试。无 nav / 无 sidebar。"""
    case = store.get_case(case_id)
    if not case: raise HTTPException(404)
    latest = store.latest_report(case_id)
    if not latest: raise HTTPException(409)
    html = _render_print_template(case, latest["payload"])  # Jinja2-style 占位替换
    return HTMLResponse(html)
```

### 2.3 · 打印模板（新建 2 文件）

- `backend/app/static/print/case-report.html`：A4 单文件（参考 `docs/UI_v01/12-pdf-cover.html` + `13-pdf-continuation.html` 的 `.sheet` 内部结构——只取 `.sheet` 节点，**丢掉 `.frame` / `.caption` / `.pdf-meta` 这些外壳与暗色预览容器**）
- `backend/app/static/print/case-report.css`：`@page { size: A4; margin: 25mm 20mm; }` + 苹方 SC `@font-face` + 全部 `.sheet` 段样式
- 占位变量：`{{ case.title }}` / `{{ case.id }}` / `{{ case.scenario_label }}` / `{{ case.target_market }}` / `{{ review_date }}` / `{{ verdict_zh }}` / `{{ verdict_summary }}` / `{{ documents[] }}` / `{{ findings[] }}` —— 由 `pdf_render.py` 的 `_render_print_template()` 渲染（用 `str.replace` 或 Jinja2 二选一，看你便利；项目已有 Jinja2 就用 Jinja2）

---

## 3 · PDF 版式（严格按 spec §8.2）

- A4 纵向 210 × 297mm / 上下边距 25mm / 左右边距 20mm
- body 11pt / heading 14pt / hero 24pt / 苹方 SC（无衬线）
- 单色 Action Blue `#0066cc` 印刷下保留（链接 / chip 边）
- **灰度打印必须可读**——状态用「色块 + 实/虚线 + 实/网纹 glyph」三重编码（参考 13-pdf-continuation `.sev-badge.warn` 用虚线 + 网纹 glyph 区分 warn）
- **禁止 `backdrop-filter` / `box-shadow` / `filter: blur`**（chromium PDF 渲染会糊）

---

## 4 · PDF 内容（严格按 spec §8.3 ASCII 图，D37 四件套）

```
抬头小字（"化工合规预审 · 审查报告"）
案件标题（24pt 600）
Case 编号 · 审查场景 · 目标市场 · 审查日期
───────────────────────
审查结论
┌─────────────────────────────┐
│ [verdict_zh chip + glyph]  一句话总结 │
└─────────────────────────────┘
───────────────────────
资料清单
- {filename} · {document_type 中文} · 置信度
- ……
───────────────────────
不合规事项（共 N 项）
[01] 违反规则 {rule_id}
     "{rule_quote}"                      [严重度 chip]
     用户原文："{user_quote}"
     改进建议：{suggestion}
[02] ……
───────────────────────
审查员 _________   签字日期 _______
复核员 _________   签字日期 _______
───────────────────────
页脚：Case 编号 · 生成时间 · 第 N / N 页（chromium 自动算页）
```

**verdict_zh 映射**：`pass`→"可审"、`needs_review`→"需复核"、`needs_supplement`→"待补"、`not_approved`→"不可审"。

---

## 5 · 不进 PDF（spec §8.5 严格）

- ❌ RAG 命中切块 / TopK / Rerank 分数
- ❌ 多 Agent 分支 trace
- ❌ 内部规则库版本号 / Manifest 指纹（设计稿里 12-pdf-cover 的 `.pdf-meta` 那堆 chip "规则库 v2026.05 内嵌" / "PingFang SC 子集嵌入" / "灰度可读 · 已校验" **不要进 PDF**，那些只是设计稿暗场预览的外壳）
- ❌ 任何 v1.X / changelog / 方案 A/B 标签
- ❌ 内部品牌字样

---

## 6 · 依赖

`pyproject.toml` 的 `[project.optional-dependencies]` 增加：

```toml
pdf = ["playwright>=1.40.0"]
```

或加入主依赖（项目主线只一个产物时优先主依赖，避免用户漏装）。

**安装后必须跑一次**：`playwright install chromium` —— 在 `IMPLEMENTATION_LOG.md` 明确记下这条命令 + 大致下载大小（≈170MB），方便用户重现。

**不引入 Node / puppeteer / npm**——Python 生态选 Playwright，自带 chromium driver。

---

## 7 · 错误兜底

| 触发 | 状态码 | Body |
|---|---|---|
| chromium 启动失败 / playwright 未装 | 500 | `{"error": "PDF renderer not available", "hint": "运行 playwright install chromium"}` |
| `case_id` 不存在 | 404 | `{"detail": "Case not found"}` |
| Case 未完成预审 (`store.latest_report()` 为 None) | 409 | `{"error": "Case has no completed review yet"}` |
| 模板渲染异常 | 500 | `{"error": "Template render failed", "case_id": ...}` |

---

## 8 · Anti-vision（严格遵守）

- ❌ 不碰 `chemical_rag.py` / `service.py` / `store.py` / `vector_store.py` / `models.py`
- ❌ 不动 `settings.py` / `ai_clients.py`
- ❌ 打印模板不能引入 RAG 证据 / Agent 分支 / 规则匹配 TopK 等管理端字段（spec §8.5）
- ❌ **不替前端实现 PDF 触发按钮**——4c Agent 负责前端按钮 + `window.open` 调用
- ❌ 不引入 npm / Node 进程；不引入除 Playwright 之外的第二个 PDF 库（weasyprint / reportlab 都不要）
- ❌ 不动 `docs/UI_v01/*.html` 任何文件（read-only 参考）
- ❌ 不要 git push / 建分支 / commit

---

## 9 · 验收

- [ ] `python -m compileall backend/app` exit 0
- [ ] `python -m pytest` 全过（不要为了 pass 删测试或加 skip）
- [ ] `uvicorn app.main:app --app-dir backend --port 8888` 起服务无 import error
- [ ] `curl -sI http://127.0.0.1:8888/api/cases/<existing-case-id>/report.pdf` → `200` + `Content-Type: application/pdf` + `Content-Disposition: attachment; filename=...`
- [ ] 下载下来的 PDF 用阅读器打开，视觉与 spec §8.3 + 12/13 设计稿 `.sheet` 内部对齐
- [ ] 黑白打印走一遍（系统打印对话框选灰度）：主结论 chip / status 色块 / 链接均可读
- [ ] case 无 `latest_report` 时 → `409` + 错误 JSON
- [ ] `case_id` 不存在 → `404`
- [ ] chromium 故意卸载（或 mock import error）→ `500` + 安装提示
- [ ] 浏览器控制台无 error；服务端日志无 stack trace

---

## 10 · 回传

### 10.1 · `IMPLEMENTATION_LOG.md` 顶部追加

```markdown
## 任务 #3f · 2026-05-13 HH:MM · UI Phase 2f PDF 后端 Playwright 渲染

**Done**
- 新建 backend/app/pdf_render.py（N 行）
- factory.py 新增 /api/cases/{id}/report.pdf + /print/cases/{id}/report
- 打印模板 static/print/case-report.{html,css}
- pyproject.toml 加 playwright 依赖；记录 `playwright install chromium` 命令

**Decisions**
- 单例 browser context vs 每次新启动：选 ...（理由）
- Jinja2 vs str.replace：选 ...（理由）

**Blockers**：无 / 具体描述

**Next**
- 等 4c 报告页接 `window.open` 触发链路打通
```

### 10.2 · `NEW_TRAPS.md` 顶部追加

记录 Playwright/chromium 装机踩坑（如 WSL 缺 libnss3 / fonts-noto-cjk 缺失导致中文豆腐块 / sandbox 在 root 下需 `--no-sandbox` 等）。

---

## 11 · 边界

- 不 git commit / push / 建分支
- 不动 `.env`
- 不访问 Windows `E:/AI/Mulit-agents/`
- 范围内自相矛盾 → 写 Blocker 停手等用户

---

**OrbitOS 签名**：徐钰 / OrbitOS Agent · 2026-05-13 · 决策依据 [[化工合规RAG工具#D44]]⑤⑥⑦
