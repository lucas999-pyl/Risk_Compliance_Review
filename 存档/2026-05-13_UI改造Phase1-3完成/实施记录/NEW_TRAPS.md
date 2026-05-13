> 开发过程中遇到的"踩坑 / 反直觉 / 容易反复的事项"，按编号倒序记录（最新在顶）。
> OrbitOS 通过 `/sync-dev chemcompliance` 主动拉取，解析后落入 `brain/40_知识库/` 或项目页 Progress。
>
> **格式**：`## TRAP #N · YYYY-MM-DD · <一句话陷阱名>`，四段式（现象 / 根因 / 修法 / 教训）。
>
> **桥接协议 v2.1**：本文件由开发端写、OrbitOS 经 `/sync-dev` 拉取，OrbitOS 不主动改。

---

## TRAP #2 · 2026-05-13 · HTTP header 不能塞中文，Content-Disposition 直写 filename="<中文>" 会 500

**现象**
- `Response(..., headers={"Content-Disposition": f'attachment; filename="{中文}.pdf"'})` → starlette `init_headers` 把 value 强转 latin-1 → `UnicodeEncodeError` → 整条响应 500。
- 出现在 sub-Agent F 的 PDF 路由 `/api/cases/{id}/report.pdf` 落地中。

**根因**
- RFC 7230 规定 HTTP header value 默认 latin-1；现代规范允许非 ASCII 但要走 RFC 5987 编码（`filename*=UTF-8''<urlencoded>`）。starlette 一律按 latin-1 编 → 见中文就炸。

**修法**
- 双 filename 兜底：`Content-Disposition: attachment; filename="case_xxx_report_YYYYMMDD.pdf"; filename*=UTF-8''<urlencoded 中文>`。ASCII 旧客户端走前者，现代浏览器（≥IE10）走后者拿到中文名。

**教训**
- 任何往 HTTP header 塞非 ASCII 字符的场景都得 RFC 5987 编码（cookie 名 / 文件名 / 自定义 header）。Python 侧用 `urllib.parse.quote` + 模板。

---

## TRAP #3 · 2026-05-13 · WSL 默认无 CJK 字体，Playwright/Chromium 渲 PDF 中文成空白

**现象**
- sub-Agent F 用 Playwright chromium 渲打印 HTML → PDF，初版输出体积小（~18 KB），用 pypdf extract 出来一堆空格，所有中文字形都是空白。

**根因**
- chromium 走 fontconfig，WSL 默认只有 DejaVu Sans 等西文字体，无任何 CJK 字形；`@font-face` fallback 到 system-ui 也找不到 → 中文字符全部用 missing glyph 渲染。

**修法**
- `sudo apt install -y fonts-noto-cjk` → fontconfig 自动 trigger，无需重启 chromium，下次 `browser.new_context()` 即拾到。修复后 PDF 体积涨到 186 KB（CJK 字形子集嵌入），文字 extract 正常。
- 模板字体栈优先级：`"PingFang SC", "Noto Sans CJK SC", "SF Pro Text", system-ui, ...`。

**教训**
- 任何容器/CI/WSL 部署 Playwright 链路，CJK 字体是隐式系统依赖。docs / README / Dockerfile 必须显式写明 `fonts-noto-cjk` + `playwright install chromium` 双依赖。
- "渲染管线无报错但产出空白"是字体缺失的典型表征，不要先怀疑 CSS。

---

## TRAP #4 · 2026-05-13 · 后端 Case schema 缺 `phase / next_step` 字段，HANDOFF §5 假定其存在

**现象**
- HANDOFF #4a §5 用 `phase` / `next_step` 决定 Case 卡片状态文案和 wizard 跳转步号，但 `backend/app/store.py:235-249` / `models.py:23-28` 实际返回的 case 只有 `id/title/status/latest_verdict/...`，无这两字段。

**根因**
- spec 写在 schema 前面：UI 设计稿假定后端会扩展多阶段字段，但 Phase 1 数据模型还没动。

**修法**
- 纯前端用 `latest_verdict + status` 组合映射 5 状态桶（case-board/index.js `mapCardStatus()`），注释「后端无 phase/next_step，按 latest_verdict + status 推断」。

**教训**
- HANDOFF 拿到手，第一步是把里面提到的字段名 grep 一遍 schema/models/store，确认存在再开工；不存在则 (a) 等后端扩字段 (b) 用现有字段推断 (c) 写 Blocker。本案选 (b)，留注释方便后端就绪后改一处。
- 后续 Wizard 多阶段状态机如需 `phase`，需新开 HANDOFF 在 `CaseRecord` 加列并迁移 DB。

---

## TRAP #1 · 2026-05-13 · 测试硬绑 settings 旧属性名 `openai_compatible_*`，不能按 HANDOFF "可以删除"直删

**现象**
- HANDOFF #1.2 §3.3 写「旧字段 `openai_compatible_base_url` / `openai_compatible_api_key` **可以删除**」，但 `backend/tests/test_demo2_rag_stack.py:217-218` 直接断言 `settings.openai_compatible_base_url == ...` / `settings.openai_compatible_api_key == ...`，删字段 → pytest 炸。

**根因**
- pydantic-settings 的 `AliasChoices` 只决定字段读哪个 env var，**不会让两个不同名的字段共享同一个 Python 属性**。新增 `chem_rag_embedding_base_url` 即便 alias 了 `OPENAI_API_BASE`，也无法替代 `settings.openai_compatible_base_url` 这个属性名本身。
- 测试断言的是属性名（编译期符号），不是 env var 名（运行期字符串）。

**修法**
- 保留 `openai_compatible_base_url/_api_key` 旧字段不动，新增 4 个 CHEM_RAG_*_BASE_URL/API_KEY 字段并列存在；两组都从 `OPENAI_API_BASE/OPENAI_API_KEY` 读 fallback。新老属性各自独立、互不替代，测试与新逻辑都满足。
- 业务侧（factory / chemical_rag）只读新字段，老字段仅供测试 / 历史 docs 引用。后续真要删，得先改测试，分两个 HANDOFF 推。

**教训**
- "字段可以删除"这种 HANDOFF 措辞，落地前必须 `grep` 一下属性名在测试/docs/其他 import 处的引用面，再决定是真删还是仅"业务侧不再使用"。
- pydantic 的 alias 系统只影响入站映射，不能用来给字段做"重命名兼容"。要重命名属性名，必须改所有读它的代码。

<!-- 等待开发端首条 TRAP 记录 -->
