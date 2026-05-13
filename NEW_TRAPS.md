> 开发过程中遇到的"踩坑 / 反直觉 / 容易反复的事项"，按编号倒序记录（最新在顶）。
> OrbitOS 通过 `/sync-dev chemcompliance` 主动拉取，解析后落入 `brain/40_知识库/` 或项目页 Progress。
>
> **格式**：`## TRAP #N · YYYY-MM-DD · <一句话陷阱名>`，四段式（现象 / 根因 / 修法 / 教训）。
>
> **桥接协议 v2.1**：本文件由开发端写、OrbitOS 经 `/sync-dev` 拉取，OrbitOS 不主动改。

---

## TRAP #8 · 2026-05-14 · KNOWN_SUBSTANCES 只有 9 条 demo 物质，扩业务 case 必须扩

**现象**
- demo 4 case 配方共用了 ~25 个 CAS，原 `chemistry.py:DEFAULT_SUBSTANCE_DATA` 只有 9 条
- 即便 SDS / 配方 / 工艺全合规，只要配方有 CAS 不在 KNOWN_SUBSTANCES，就触发 `unknown_substance_review` → chief_verdict 判"复核" → customer_verdict needs_review
- case_pass 配方 9 项 8 项 unknown → 全合规却跑成"复核"

**根因**
- KNOWN_SUBSTANCES 是 demo 时期写死的 9 条小集合，但是 `_base_rule_hits` line 1782 业务逻辑：
  ```python
  elif components and all(component["known"] for component in components):
      formula_components_known
  elif components:
      unknown_substance_review  # any unknown 即触发
  ```
- 没有"按 CAS 主数据库分级"机制，要么全 known 要么 unknown

**修法**
- 扩 `chemistry.py:DEFAULT_SUBSTANCE_DATA` 加 20 条涂料/油墨常见物质（钛白粉 / 丙烯酸乳液 / HEUR / 甲苯 / 乙酸乙酯 / 双酚 A 环氧 / 颜料黄 等）
- 多数标 `tsca_active_demo` + `low_hazard_demo`；可燃溶剂标 `china_hazardous_demo` + `flammable_demo` 保留 review 路径触发能力
- 不动 unknown_substance_review 触发逻辑（保留 demo 业务语义）

**教训**
- demo 数据资产扩域时，**配方组分主数据库**是必须同步扩的对象，不能只扩规则 pack
- 后续如要做"真实 RAG 命中"路径，应该改成"按 CAS 在向量库查命中后判 known"，不再依赖硬编码集合

---

## TRAP #7 · 2026-05-14 · `_storage_value` 只查 process / formula，SDS 第 7 章正文不在扫描范围

**现象**
- case_pass 的 SDS 第 7 章明明写了「储存条件：5°C – 35°C 阴凉避光储存」，但 `document_quality` 仍判 `storage_condition: missing`
- 单点 missing 命中 `blocking_fields`（包含 `storage_condition`）→ document_quality.status = needs_supplement → customer_verdict 兜底 needs_supplement
- 这是 case_pass 跑出 needs_supplement 的最后一根稻草（前面 SDS 章节 / 配方表抽取已全修通）

**根因**
- `_storage_value(process, formula)` 只在 process.fields（PROCESS_EXTRA_FIELD_PATTERN 命中的）和 formula.text 行首找
- SDS 第 7 章正文里的「储存条件: ...」由 `parse_document_text` 切到了 `sections[6].content`，没被这个函数扫到

**修法**
- 扩签名 `_storage_value(process, formula, parsed_sds=None)`，在 process / formula 找不到时遍历 `parsed_sds.sections` 取 number==7 的 content 扫「储存条件 / 储存类别 / 储运条件」前缀行
- callsite `_review_checklist:3005` 传入 parsed_sds

**教训**
- SDS 是结构化分章的，关键字段不应只在 "field: value" 平面行扫描，要按章节范围找
- blocking_fields 集合（line 2428）是单点击杀，添加新业务字段前要确认 _check_item 的判定足够鲁棒

---

## TRAP #6 · 2026-05-14 · pytest evaluate 路径 ≠ 浏览器 upload 路径（两条 parser 流不同）

**现象**
- pytest `test_evaluation_does_not_call_remote_llm` 跑 4 case verdict_match_rate `0.9375`（15/16）
- 同样 4 个文件，浏览器走 wizard 上传跑 4 case verdict 全坍缩到 `needs_supplement`
- pytest "近通过" 让人误以为 demo 数据可用，但用户真正演示走的是浏览器路径

**根因**
- **evaluate 路径**：`/chemical/evaluation` → `evaluate_dataset()` → `run_trace(case_id)` → `run_from_documents(sds_text, formula_text, process_text)` —— 直接读 manifest 的文件路径，给 `parse_document_text` 抽 sections + components，绕过 upload 路径的角色识别
- **upload 路径**：`/chemical/cases/{id}/documents` → `uploaded_document_from_bytes` → `_classify_uploaded_package`（启发式识别 SDS/配方/工艺）→ `build_package_precheck`（按 SDS 16 章模板比对，0/16 命中 → document_completeness_precheck 全触发 → overall_status="partial" 但 document_quality 仍走 blocking_fields）
- 两条路径**共享** `parse_document_text` / `_parse_formula` / `_parse_process` 等底层 parser，所以底层修一处两边同步生效

**修法**
- 不是修两套 parser，而是扩 `parse_document_text` 内的 `SECTION_PATTERN` / `extract_components` markdown table fallback / `TEMPERATURE_PATTERN` 加 `°C` / `_parse_process` fallback / `_storage_value` 加 SDS 第 7 章扫描
- 关键认识：底层 parser 修通后，两条路径自动对齐

**教训**
- 验收 demo 时**必须走真实用户路径**（浏览器上传 → 看报告），不能只用 pytest 替代
- pytest 跑通的"业务流"可能跳过了用户实际触发的代码段（如 _classify_uploaded_package + build_package_precheck）
- 下次写 HANDOFF 验收口径时，要分清 "pytest 路径" 与 "UI 路径"，两者都列

---

## TRAP #5 · 2026-05-14 · `.md` 与 `.txt` 格式差异让所有正则集体失效

**现象**
- 老 demo 用 `*_sds.txt` 写"`1. 化学品及企业标识`"格式章节标题，老 `*_formula.txt` 用"`乙醇 CAS 64-17-5 45%`"行式配方
- 新 demo（sub-X）用 `sds.md` / `formula.md` / `process.md` 配 markdown：`## 第 1 章 化学品及企业标识` / `| 1 | 乙醇 | 64-17-5 | 45 |` markdown 表格 / `## 1. 工艺简介` 段落
- 结果：`SECTION_PATTERN` / `FORMULA_COMPONENT_PATTERN` / `PROCESS_FIELD_PATTERN` / `TEMPERATURE_PATTERN` 老正则**全部失效**，SDS 抽到 0 章 / 配方抽到 0 component / 工艺字段抽到 0 个 / 温度 ℃ 命中但 °C 不命中

**根因**
- 老正则只针对老格式优化：`^\s*\d[\.\)]\s*xxx`（数字 + 点 / 括号）、`^\s*<name>\s+CAS\s+\d+-\d+-\d`（空格分隔）、`\d+\s*(C|℃)`（unicode 度数符号 `°` 没考虑）
- 新格式 markdown 表格行 `| 1 | 名 | CAS | ... |` 整行不带 "CAS" 字面值，老 pattern 100% 不匹配
- 温度 `50°C` 中的 `°` 把 `\s*` 与 `C` 隔开，老正则不认

**修法**
- `SECTION_PATTERN` 扩成 `(#+\s*)? (第\s*)? (1[0-6]|[1-9]) (\s*章)? [\.\)：:]?\s+ 标题`，老 `1.` 与新 `## 第 1 章` 都认
- `extract_components_from_markdown_table` 新函数：扫连续 `|...|` 行块，识别表头 "CAS"/"含量"/"中文名" 列，按列索引抽 component
- `TEMPERATURE_PATTERN` 改 `\d+(?:\.\d+)?\s*°?\s*(?:C|℃)\b`，加 optional `°` 与 word boundary
- `_parse_process` 加 fallback：温度从 TEMPERATURE_PATTERN min-max / 压力扫 `\d+\s*(MPa|kPa|bar|atm)` 或"常压" / 关键步骤扫 markdown step heading 计数 + `工艺步骤`/`工序` 字眼

**教训**
- 新增 demo 数据格式（`.md`）前，先 grep 项目里所有正则看是否兼容 —— 否则容易踩"老 case 通过、新 case 全挂"
- markdown 是结构化文本但**单行无关键字**（表格行不带列名），不能套老的 "key: value" 平面行 pattern
- 温度 / 压力 / 浓度等数值字段的单位符号要考虑 unicode 全形态（`℃` / `°C` / `C` 全要兼容）

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
