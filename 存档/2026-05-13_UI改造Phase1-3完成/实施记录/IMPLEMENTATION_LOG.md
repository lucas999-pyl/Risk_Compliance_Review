> 每轮任务完成后在此处上方追加新记录（最新在最上面）。保留最近 10 轮详细记录，更早的压缩到底部「归档」段。
> 格式：`## 任务 #N · YYYY-MM-DD HH:MM · <一句话总结>`，四段式（Done / Decisions / Blockers / Next）。
>
> **桥接协议 v2.1**：本文件由开发端（WSL 内执行 Agent）维护，OrbitOS 晨间通过 `/start-my-day` 增量拉取，按 `exec_last_synced` 筛选 → 嵌入当日日记「相关项目」段。OrbitOS 只读不写。

---

## 任务 #4 · 2026-05-13 18:30 · UI 改造全收完 · 集成 smoke

**完成 / Done**
- Phase 2 单条消息内 spawn 6 个 sub-Agent，全部 return 成功，文件域 0 冲突（factory.py 仅由 sub-Agent F 追加 2 路由 + 3 个 import，原 26 条业务路由未动）
- 集成 smoke 全过：
  - `python -m compileall backend/app` exit 0
  - `python -m pytest` **79 passed in 25.53s**
  - uvicorn 在 `127.0.0.1:8888`（PID 42135，sub-Agent F 重启后的实例）
  - 9 路由 curl 全部 200：`/` 657 B 新壳 / `/legacy` 99607 B 老 UI / `/static/pages/case-board/index.js` 10656 / `wizard` 3279 / `report` 23688 / `admin-kb` 16079 / `admin-trace` 23479 / `/api/cases/case_934c906c2ede/report.pdf` 186554 B + `application/pdf` + `%PDF-1.4` magic / `/cases/case_934c906c2ede/print` 2148 B + `text/html`
  - 无 latest_report 的 Case 走 409（F 已实现错误兜底）
- 7 条目测路由（curl-level smoke 等价目测，UI 渲染需要主 Agent 手动浏览器访问；以下确认 server-side 资产已就位）：
  - `http://127.0.0.1:8888/` → 200 / 新壳 HTML（含 `.frame` grid + `<main id="route-outlet">`）
  - `http://127.0.0.1:8888/legacy` → 200 / 老 UI 99607 B
  - `#/cases` → case-board/index.js 200 + 10656 B
  - `#/cases/new?step=1`~`?step=5` → wizard/index.js 200 + 3279 B（多文件拆分，主入口）
  - `#/cases/<id>` → report/index.js 200 + 23688 B
  - `#/admin/kb` → admin-kb/index.js 200 + 16079 B
  - `#/admin/cases/<id>/trace` → admin-trace/index.js 200 + 23479 B
  - `/api/cases/<id>/report.pdf` → 200 + application/pdf + 186554 B（PDF magic ok）

**决策 / Decisions**
- LOG 汇总顺序：按 #3a → #3b → #3c → #3d → #3e → #3f 倒序写（#3f 在最顶，#4 在 #3f 之上的全局收尾段），与 master HANDOFF Step 3.1 一致
- sub-Agent E（admin-trace）违反指令直接写过一段 #3e 到 LOG，已清理；以本汇总的 #3e 段为准（内容等价，由主 Agent 串行统一收口）
- factory.py 改动总览：Phase 1 加 3 处（StaticFiles import + mount + `/legacy` 路由），Phase 2-F 加 3 处（datetime / HTMLResponse / JSONResponse import + `/cases/{id}/print` + `/api/cases/{id}/report.pdf`），共 6 处增量，原有 26 条业务路由 0 触碰
- Phase 3 集成 smoke 用 case `case_934c906c2ede` 作 PDF 联调主样本（数据库里已有 latest_report 的 case），其他无 latest_report 的 case 走 409 兜底验证

**阻塞 / Blockers**：无

**下一步 / Next**
- 主 Agent 已交付到用户验收：建议用户在浏览器跑一次 `http://127.0.0.1:8888/`，按 sidebar 切到管理端、走 Wizard 5 步、看报告 3 态、下载 PDF
- 用户验收时若发现某页 console 报错，可指定 sub-Agent X 用 SendMessage 接续修复（不需要 spawn 新 Agent）
- 文档 / 部署侧未做：sub-Agent F 留了 TRAP「生产环境需装 fonts-noto-cjk + playwright install chromium」，建议下一轮 HANDOFF 涵盖

---

## 任务 #3f · 2026-05-13 · UI Phase 2-F PDF 后端 Playwright 渲染

**完成 / Done**
- 新建 `backend/app/pdf_render.py`（≈350 行）：单例 chromium browser（asyncio.Lock 守护启动一次） / `render_case_report_pdf(case_id, store, base_url)` 主入口 / `build_print_html(case, payload, documents)` 同步构造打印 HTML / `PDFRendererUnavailable` / `CaseNotReady` 业务异常 / verdict_zh 映射（pass→可审 / needs_review→需复核 / needs_supplement→待补 / not_approved→不可审）/ 灰度三重编码 verdict_css / severity_css / `_esc()` HTML 转义 / `str.replace` 无 Jinja2 依赖
- 新建打印模板 `backend/app/static/print/case-report.html` + `case-report.css`：A4 / `@page` 25mm×20mm / PingFang SC + Noto Sans CJK SC 字体栈 / `.sheet` / `.conclude-box` / `.file-list` / `.pf-find` / `.signoff` / `.disclaimer` 与设计稿 12-pdf-cover / 13-pdf-continuation 的 `.sheet` 内部对齐 / 灰度三重编码 badge（实/虚/点/双线 + 实/网纹/水平网纹/实心 glyph）
- 修改 `backend/app/factory.py`：仅追加 import（`datetime` / `HTMLResponse` / `JSONResponse`）+ 2 路由：`GET /cases/{case_id}/print` → HTMLResponse；`GET /api/cases/{case_id}/report.pdf` → application/pdf + RFC 5987 中文文件名；原 26 条业务路由完全未动
- 系统依赖装好：`pip install playwright` + `python -m playwright install chromium`（170 MB + 112 MB）+ `apt install fonts-noto-cjk`（CJK 字体栈）
- 验收：`/health` 200 / PDF 200 + 186 KB + CJK 文字可 extract / print HTML 200 / compileall 0 / pytest 79 pass / case `case_934c906c2ede` 联调成功

**决策 / Decisions**
- 单例 browser vs 每次新启：前者复用 chromium 进程省 1-2 s 冷启，`new_context()` 仍按请求隔离
- `str.replace` 模板 vs Jinja2：项目主依赖无 Jinja2，免增依赖，所有占位走 `_esc()` HTML 转义
- 路由 `/cases/{id}/print` 与 `/api/cases/{id}/report.pdf` 两条独立命名，互不冲突；遵服用户在 prompt 指定的路径
- Content-Disposition 用 RFC 5987 `filename*=UTF-8''<urlencoded>` 双 filename，老浏览器走 ASCII fallback、新浏览器拿到「审查报告」中文名
- 错误码：404（Case 不存在）/ 409（无 latest_report）/ 500（playwright 未装或 chromium 启动失败，附 hint）

**阻塞 / Blockers**：无

**下一步 / Next**
- 前端 4c 报告页接入 `window.open("/api/cases/" + id + "/report.pdf")` 已就绪
- 生产部署需在 docs / README 标注：`fonts-noto-cjk` + `playwright install chromium` 双依赖

---

## 任务 #3e · 2026-05-13 · UI Phase 2-E Admin 审查回放

**完成 / Done**
- 新建 `backend/app/static/pages/admin-trace/{index.js, admin-trace.html, admin-trace.css}` 三件套
- `mount(outlet, params)` 接 `api.cases.get(caseId)` 拿 case + latest_report；首行做 role 防御性闸门
- 顶部元信息条（case 编号 · 场景 · 市场 · 审查日期 + 34px 标题 + sub + 5 chip + 「导出 trace JSON」「返回客户视图」）
- 左栏 320 px 时间线：`latest_report.nodes` 数据驱动 N 节点（项目实际 10 节点：load_task / parse_sds / parse_formula / rag_retrieve / material_agent / process_agent / storage_agent / regulatory_agent / cross_check / chief_review）；每节点 dot + name + summary + 耗时；点击切右栏，加 `.active`；running 加 `.spinner`
- 右栏详情：34 px ttl + sub 行（耗时 / status / 节点特化字段）+ 4 `<details class="trc-panel">` 默认折叠：①查询构造 ②TopK 命中（`report.retrieval.chunks` 反查 vec/rerank/snippet）③input/output JSON 摘要（>8 KB 截断）④Agent 分支推理链
- 空态（无 case / 无 latest_report / nodes 为空）走 `.trc-empty` 而非白屏；导出 trace JSON Blob 下载

**决策 / Decisions**
- 节点数从设计稿固定 10 改为数据驱动 N，sub 用 `${nodes.length} 节点全链路 trace`，防与后端 `nodes` 长度漂移
- role 键统一走 `window.shell.getRole()`（实际 `rcr.role`），兼读 HANDOFF 简写 key
- `_agent` 节点 TopK 用 `retrieved_chunk_ids` 反查求交，`rag_retrieve` 节点直取前 10
- 默认激活第一个非 completed 节点（聚焦排错），全 completed 回落到 [0]

**阻塞 / Blockers**：无

**下一步 / Next**：等浏览器手测时切 admin 视角访问 `#/admin/cases/<id>/trace` 验渲染

---

## 任务 #3d · 2026-05-13 · UI Phase 2-D Admin 知识库

**完成 / Done**
- 新建 `backend/app/static/pages/admin-kb/{index.js, admin-kb.html, admin-kb.css}` 三件套
- 移植设计稿 `10-admin-kb.html` 的 `.frame > .main`：`.adm-hd`（标题 + lead + 4 Pill 工具）+ 4 张 metric 卡（source / chunk / vector / embedding 模型）+ 已索引规则表
- 接全部 KB API：`status` 驱 metric 卡 + 空态 hint / `chunks` 聚合为规则行 / `search` 检索框 + 市场 ckb + topK=5 / `importDemoPack` / `uploadPack` modal + 双 dropzone / `clear` 双确认 modal / `sourcePackZip` 下载
- 双确认清空：第一道 `window.confirm` → 第二道输入 `CLEAR` 才解锁 `cta-dark` 确认
- mount 时 `hideProgress()` + `setStepbar("知识库管理")` + `setCrumb`；adminOnly 闸门由 shell.js PAGE_MAP 把关

**决策 / Decisions**
- 清空按钮选 ink `cta-dark` 而非红色，遵循 Apple HIG「不用红色按钮」
- `chunks` → 规则列表客户端聚合，字段名做 4-级 fallback（`metadata.rule_id` → `rule_id` → `source` → `id`），兼容 schema 漂移
- `.cta-dark` / `.cta-pearl` 在 shell.css 暂无定义，本页 admin-kb.css 内补回，避免裸 `<button>`；待后续多页复用时再抽到 shell.css

**阻塞 / Blockers**：无

**下一步 / Next**：浏览器手测 admin 角色访问 `#/admin/kb`；schema 漂移时收紧 fallback

---

## 任务 #3c · 2026-05-13 · UI Phase 2-C 报告 3 态

**完成 / Done**
- 新建 `backend/app/static/pages/report/{index.js, report.html, report.css}` 三件套（~700 行）
- 3 态串通 `api.cases.get(caseId)`：(1) 无 `latest_report` → 「未生成」空态 + 「运行预审」CTA；(2) 有报告且 `case.range_dirty !== true` → 默认态（主结论卡 + 状态条 chips + 四件套清单 + 抽屉）；(3) `range_dirty === true` → mute hero + 灰化清单 + warn alert-strip + 「重新运行预审」CTA
- 客户/管理员视角联动：`role-admin` class + CSS `:not(.role-admin) .admin-only{display:none}`；hero `.foot` / `.evi`「查看证据」/ 抽屉 3 个 admin tabs（RAG 证据 / Agent 分支 / 规则匹配）admin only
- PDF 下载：`window.open('/api/cases/:id/report.pdf')` + 3 s loading 反馈
- 抽屉：CSS `transform: translateX(100%) ↔ 0` + 300 ms transition；icon-btn 切 `.drawer-open` class
- 错误兜底：Case 不存在/网络错 → 红错误页 + 返回 Case 看板按钮，杜绝白屏
- 重跑：`api.cases.runReview` + spinner subtask runcard + 完成后 `refreshCases`

**决策 / Decisions**
- 抽屉用 body class 切换而非独立路由（HANDOFF 明文）；transform 不破 `.frame` grid stacking
- findings 数据源优先 `customer_report.issue_groups[].items[]`（D37 四件套），fallback 到 `latest_report.findings[]` 并过滤 `chemical_verdict` 自指条目，让 verdict=合规 演示 Case 干净显示「无不合规事项」气泡
- 主结论卡仅非 mute 态加 box-shadow，严守「页面唯一 shadow」约束
- step bar 调 `hideProgress()`（设计稿 07/08/09 全是 `.frame.no-progress`），边到边视觉

**阻塞 / Blockers**：无

**下一步 / Next**：4f PDF 后端已 land，点击下载实测可下到 186 KB PDF；待 Case 数据加 `range_dirty` 字段时自动激活 rerun 态（兼容路径已留）

### TRAP-3c-1 · import.meta.url 解析路径协议
`new URL("./report.html", import.meta.url).pathname` 在 http:// 下返绝对路径可直 fetch；file:// 下需二次处理。当前 uvicorn 走 http:// 没问题。

### TRAP-3c-2 · role 切换 FOUC
shell.js `setRole` 触发 hashchange → `outlet.innerHTML=""` → 重 mount 中间 ~100 ms 空白。本页 `.loading-state` slot 兜底，无 admin 元素短暂闪现。

---

## 任务 #3b · 2026-05-13 · UI Phase 2-B Wizard 5 步

**完成 / Done**
- 新建 `backend/app/static/pages/wizard/`：`index.js`（mount 入口 + 补注册 `#/cases/:id/new`）/ `wizard.css`（10.5 KB，抽自设计稿 02–06 page-specific 段）/ `steps.js`（5 个 `renderStepN`）/ `precheck.js`（封装上传 → precheck 与重入加载）/ `runner.js`（Step 5 子任务驱动）
- Step 1：3 字段（title input / scenario select 4 项 / markets toggle-chips 5 国）；title 非空 + ≥1 市场才激活 CTA；提交后 `api.cases.create` → 跳 `#/cases/<id>/new?step=2` + `shell.refreshCases()`
- Step 2：dropzone（drag&drop + 点 + 按钮）+ 上传列表（图标 / 大小 / 进度条 / 状态 chip）；`api.cases.uploadDocuments` 同步返回 `package_precheck`；400 ms 后自动跳 Step 3
- Step 3：4 张 metric 卡 + file-ident 明细；`overall_status` 异常或有 blocked/limited/supplement_actions 时显 alert-card + 「上传补件」回 Step 2，CTA 改「已知悉，继续」
- Step 4：4 大类 18 项 scope-row（7 接后端 check_type id，11 演示用）；推荐项默认勾选；每组「恢复推荐 / 全不选」；stepbar 实时「已选 N / 共 18」
- Step 5：首屏中央「运行预审」Pill；点击后原地替换 runcard（% + bar + 6 子任务行）；`api.cases.runReview` 内置 ensureLoaded 兜底；视觉乐观节奏 + 真实返回快进；失败行 block 点 + 「重试」link；完成后 navigate `#/cases/<id>`
- 每屏 `setProgress(stepIdx, 4)` + `setStepbar` + `setCrumb`

**决策 / Decisions**
- pbar 按用户契约 4 段（Step 5=全部 done），与设计稿 5 段不同
- `#/cases/:id/new` 不在 shell PAGE_MAP，在 wizard/index.js 顶层 `registerRoute` 补注册
- Step 4 scope 仅前端追踪（无 update endpoint），运行预审仍按 case 创建时的 check_types 跑（D44 范围内 UI 演示）
- Step 5 子任务采乐观节奏 + 真实返回快进，spinner 反映真实 fetch 等待

**阻塞 / Blockers**：无

**下一步 / Next**：等用户跑端到端验证；4c 已 land 可联调

### TRAP-3b-1 · 直接刷新 `#/cases/:id/new?step=N` 走 router 404
本路由由 wizard/index.js 在 import 时补注册，shell 只在 PAGE_MAP 命中才会 import 本模块 → 冷启动 URL 已是带 id 的 wizard 路由时未触发加载死锁。需 sub-Agent A 在 shell PAGE_MAP 加 `"#/cases/:id/new"`，本任务域外。

### TRAP-3b-2 · fetch 上传无 progress 事件
fetch + FormData 浏览器不暴露 upload progress。setInterval 220 ms 假爬到 92 % 等响应，resolve 后置 100 %。要真实进度需换 XHR。

### TRAP-3b-3 · Step 5 Pill→runcard DOM 替换丢监听
`#wz-run-anchor` innerHTML 完全替换会丢 Pill 监听。retry link 用 `data-act="retry"` 在每次 drawCard 后重绑，不依赖旧 button。

---

## 任务 #3a · 2026-05-13 · UI Phase 2-A Case 看板

**完成 / Done**
- 新建 `backend/app/static/pages/case-board/{index.js, case-board.html, case-board.css}` 三件套（export `mount(outlet, params)`）
- 状态文案 5 桶：pass/ready_for_next_step→「可审 · 已完成」/ needs_review→「需复核 · 报告就绪」/ needs_supplement→「缺件 · 待补」补件回 wizard step=2 / not_approved→「未通过」/ draft/无 verdict→「Step 1 · 案件基本信息」→ wizard step=1
- 空态：`cases.length===0` 时居中容器（max-width 480 / 34 px / 300 weight），文案「还没有 Case，从右上角"新建 Case"开始」；CTA 始终保留在 hd 右侧
- 工具条：4-tab（全部/进行中/已完成/待重跑）+ 搜索框（120 ms debounce 真实过滤）；末位 dashed「＋ 新建一个 Case」占位卡同跳 `#/cases/new?step=1`
- 卡片 chips 基于真实字段动态生成（材料类型 / 目标市场 / 检查项数 / 文档数），不硬编码设计稿假数据
- 错误兜底：`api.cases.list()` 抛错显 `.cb-error` 条不白屏
- mount 时 `hideProgress()` + `setStepbar("Case 看板")` + `setCrumb`

**决策 / Decisions**
- 不在本模块自 `registerRoute`：shell PAGE_MAP 已映射 `#/cases`，避免双挂载；只 export mount
- 模板用 fetch 注入（vs 内联字符串）：可读、可独立审稿
- 类名加 `.cb-` 前缀：避免 `.hd/.subbar/.grid/.card` 过通用与他页冲突
- chips 改真实字段动态（vs 写死「已识别 3 / 需补 0 / 可查 6 / 阻断 1」），杜绝假数据
- 没有 box-shadow（留给报告页主结论卡）
- 整张卡片用 `<button>`（vs `<div>` + cursor），键盘可达

**阻塞 / Blockers**：无

**下一步 / Next**：等 4b 落地后验「新建 Case」+「继续/补件」跳转；等 4c 落地验「查看报告」；schema 加 phase/next_step 后改一处即可

### TRAP-3a-1 · HANDOFF §5 写的 phase / next_step 字段后端不存在
HANDOFF §5 用 `phase` / `next_step` 决定状态文案与跳转步号，但 store.py:235-249 / models.py:23-28 实际只返 `id/title/status/latest_verdict/...`。改为纯前端用 `latest_verdict + status` 推断（`mapCardStatus()`）；注释「待后端补字段后改一处」。

---

## 任务 #2 · 2026-05-13 17:50 · UI Phase 1 全局壳 + 设计 token + 路由 + StaticFiles

**完成 / Done**
- T1 · 抽 token：`backend/app/static/css/tokens.css`（943 B / 36 行）只放颜色 + 字体；字号/圆角/间距留给各页 CSS。
- T2 · 全局壳 8 个新文件 + 1 个重命名：
  - `static/index.html` 改写成 21 行壳骨架（含 `.frame` grid + #shell-nav / #shell-pbar / #shell-stepbar / #shell-side / #route-outlet）。
  - `static/legacy.html` ← `mv` 自原 99607 B 老 index.html（内容字节不变，只换名）。
  - `static/css/shell.css`（5829 B）：剥离 `.caption` 与 wizard/upload/metric/scope/runcard 段后的全局壳样式（gnav / pbar / stepbar / side / main + cta-primary / cta-ghost / cta-dark / cta-pearl / link / chip / dot）；`.frame` 改 `width:100%; min-height:100vh` 铺满（设计稿 1440 px 固定宽是给标注用的，运行时不取）。
  - `static/js/router.js`（2761 B）：导出 `registerRoute(pattern, mountFn) / navigate(hash) / getCurrentRoute() / startRouter()`，hash router，正则编译 `:param`，支持 query string，自动捕获 mount 错误。
  - `static/js/api.js`（3813 B）：封装 cases / knowledge / technology / evaluation 4 个命名空间 + `vectorStore` + `health`；`api.cases.runReview` 内置 `await api.knowledge.ensureLoaded()`，自动 detect chunk_count===0 → 调 importDemoPack，解掉老 UI 的「知识库未加载」静默闸门（LOG #1 现场补充）。
  - `static/js/shell.js`（8251 B）：渲染 nav / stepbar / pbar，定义 5 条 PAGE_MAP（`#/cases` / `#/cases/new` / `#/cases/:id` / `#/admin/kb` / `#/admin/cases/:id/trace`），dynamic import 各页模块；暴露 `window.shell.setProgress / hideProgress / setStepbar / setCrumb / refreshCases / getRole / setRole / navigate / api`；role 存 `localStorage.rcr.role`，admin-only 路由有 client-side 闸门 + 切回 client 时 fallback 到 `#/cases`。
  - `static/js/pages/.gitkeep` + `static/pages/.gitkeep`（占位空目录）。
- T3 · `backend/app/factory.py` 加 3 处（StaticFiles import / mount("/static",...) / `@app.get("/legacy")` 路由），保留原 `@app.get("/")` 不动。
- T4 · smoke 全过：`compileall` 0 exit；`pytest 79 passed in 25.60s`；uvicorn 起在 `127.0.0.1:8888`（PID 33418）；`/health` ok；7 个 curl 全 200（tokens.css 943 / router.js 2761 / api.js 3813 / shell.js 8251 / shell.css 5829 / `/legacy` 99607 / `/` 壳 HTML）。

**决策 / Decisions**
- ES Modules vs IIFE：选 ES Modules（`<script type="module">` + `import/export`），理由是 dynamic import 各页模块需要 ESM 语法，且现代浏览器原生支持，免打包器。HANDOFF Anti-vision 明确禁止任何打包器。
- hashchange vs History API：选 hashchange，理由是 FastAPI 现有 catch-all 路由复杂（多个 `/chemical/*` 业务路由），改 history API 需要后端补一条 catch-all → static/index.html 兜底，会和现有路由形状冲突；hash 派发纯 client-side，零后端改动。
- `.frame` 宽度策略：设计稿固定 1440 px 是为了标注成像。运行时改为 `width:100%; min-height:100vh`，让壳铺满浏览器视口；后续各页 wzbody 等内部容器自己用 max-width 控制可读宽度。
- 测试路径同步：`backend/tests/test_static_workbench.py` / `test_technology_demo.py` / `test_customer_review_flow.py` 共 3 处 `static/index.html` → 改为 `static/legacy.html`，2 处 `client.get("/")` → `client.get("/legacy")`。**这不是删测试或加 skip**，只是同步文件物理位置变化；测试用例语义、断言内容、断言数量 0 变化。

**阻塞 / Blockers**
- 无。Phase 2 的 6 个 sub-Agent 可以进。

**下一步 / Next**
- Phase 2：单条消息内 spawn 6 个 sub-Agent（4a Case 看板 / 4b Wizard / 4c 报告 / 4d Admin KB / 4e Admin Trace / 4f PDF Playwright）；契约依赖 router.js / api.js / shell.js 全部已就位。
- Phase 3：6 个 sub-Agent 全部 return 后，主 Agent 汇总写 LOG #3a~#3f + 集成 smoke + LOG #4。

---

## 任务 #1 · 2026-05-13 13:02 · 桥接 bootstrap + 拆双平台凭证 + 装依赖 smoke

**完成 / Done**
- 装依赖：`python -m pip install -e ".[dev]"` exit 0（新增 pydantic-settings 2.14.1、uvloop、httptools、watchfiles）。
- 改造 5 文件：
  - `backend/app/settings.py`：新增 4 字段 `chem_rag_embedding_base_url / chem_rag_embedding_api_key / chem_rag_llm_base_url / chem_rag_llm_api_key`，均用 `AliasChoices(主名, "OPENAI_API_BASE"/"OPENAI_API_KEY")`；旧 `openai_compatible_base_url/_api_key` **保留**（test_demo2 第 217-218 行硬绑这两个属性名，删除会炸测试）。
  - `backend/app/ai_clients.py`：`AIClientConfig` 末尾追加 `llm_base_url=None / llm_api_key=None`（保持原 dataclass 字段顺序，避免破坏现有 kwarg 调用）；`LLMClient._should_call_remote` 与 `_remote_chat` 改用 `self.config.llm_base_url or self.config.base_url` 与 `self.config.llm_api_key or self.config.api_key`；`EmbeddingClient` 不动（其 `base_url/api_key` 现在由 factory/chemical_rag 喂入 `chem_rag_embedding_*`）。
  - `backend/app/factory.py:48-59`：`AIClientConfig(...)` 改用 `chem_rag_embedding_base_url / _api_key` 作为 embed 凭证，新增 `llm_base_url=settings.chem_rag_llm_base_url / llm_api_key=settings.chem_rag_llm_api_key`。
  - `backend/app/chemical_rag.py:250-260`：同 factory.py 改造点同步。
  - `.env.example`：按 HANDOFF §3.4 升级为双平台模板（UniAPI Qwen embed v4 + DeepSeek V4-flash LLM）。
- smoke：`compileall backend/app` exit 0 / `pytest` **79 passed in 25.18s** / uvicorn 起服务 `/health` 返回 `{"status":"ok"}` / `GET /` 返回 200 + 99607 bytes 工作台 HTML。

**决策 / Decisions**
- 选了「最小化方案」（HANDOFF §3.5 后一种）：`AIClientConfig` 保留 `base_url/api_key` 字段语义为 embed 凭证（与现有 EmbeddingClient 行为一致），新增 `llm_base_url/llm_api_key` 走 LLMClient，未传则 fallback 到 `base_url/api_key`。理由：现有 5 处测试 `AIClientConfig(base_url=..., api_key=...)` 全用 kwargs，新字段加在末尾且带默认值不破坏调用；只有 LLMClient 内 2 行用 `or` fallback。
- 旧 `openai_compatible_base_url/_api_key` 在 settings.py 保留（HANDOFF §3.3 说"可以删除"，但 §6 又要求老 `OPENAI_API_BASE/OPENAI_API_KEY` 别名链不能断；删属性名会炸 test_demo2 line 217-218），保留是更稳的选择。
- 4 个新 CHEM_RAG_*_BASE_URL/API_KEY 字段全部把 `OPENAI_API_BASE/OPENAI_API_KEY` 列为 `AliasChoices` 第二选项，向后兼容老 .env / 老 docs。

**阻塞 / Blockers**
- 无。

**下一步 / Next**
- 等用户在 `.env` 填实际 2 把 Key（UniAPI + DeepSeek）后跑 T1d：Case 工作台创建 → 上传单文件 → 看 precheck → 跑预审 → 看报告。

**现场补充 / Runtime notes（2026-05-13 T1d 启动后增补）**
- 用户已填 `.env` 两把 Key，uvicorn 起在 `0.0.0.0:8888`（task `b8i3v7o5w`，pid 15735，持续运行中，可被下轮复用或显式 kill）。
- **T1d 第一次卡点**：用户上传资料后点"运行预审"按钮无反应。根因不在后端，而在前端闸门——`backend/app/static/index.html:1497-1500` 的 `runCaseReview` 一开头就检查 `state.knowledgeLoaded`，false 则 `setStatus("知识库未加载...") + return`，请求根本不发出，uvicorn 日志因此没有 `/run-review` 痕迹。提示文案显示在工作台底部状态条，用户没注意到。
- **修复手段**：调用 `POST /chemical/knowledge/import-demo-pack` 导入演示知识包（或在「管理端」Tab 走 UI），返回 `pack_id=chemical_rules_pack / source_count=7 / chunk_count=7 / vector_count=7 / embedding_provider=openai_compatible / embedding_model=text-embedding-v4` —— **说明 UniAPI（Embedding 凭证）真实可用，没有回落到 hash embedding**。DeepSeek（LLM 凭证）在用户随后点预审时才会被调用，本会话尚未走到那一步。
- **UX 隐患（建议下轮考虑）**：知识库为空时"运行预审"应该禁用按钮或弹明显模态，而不是只 setStatus 一行底部小字。这是 T1d 复现率最高的踩坑点。

**Hand-off 给下一轮的开发端状态**
- 5 文件改造已落地、79 tests pass、双平台凭证拆分生效（UniAPI 已验、DeepSeek 待用户实际跑一次预审验证）。
- 服务进程仍在跑（`pid 15735`，端口 8888）。下一轮 HANDOFF 如需重启服务可直接 `pkill -f 'uvicorn app.main'` 然后照原命令起。
- 知识库已带 7 条演示 chunk（用户 T1d 期间通过 API 导入），后续不需要再 import-demo-pack。
- `.env` 由用户本地填入真实 Key，开发端继续不读不改。

<!-- 等待开发端首条任务记录。HANDOFF #1 完成后由开发端在此追加 `## 任务 #1 · ...` -->
