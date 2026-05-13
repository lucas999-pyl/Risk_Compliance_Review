# 架构说明

## 当前形态

系统当前采用“模块化静态前端 + FastAPI 后端 + SQLite 本地存储 + 本地 RAG/规则引擎”的形态。普通用户通过 Case 工作台完成资料包上传、预检、审查范围确认、自动预审和报告下载；管理端用于知识库、RAG 证据、Agent 分支和 trace 排查。

## 前端架构

入口：

```text
backend/app/static/index.html
```

主要模块：

- `static/js/router.js`：hash 路由。
- `static/js/shell.js`：顶部栏、侧边栏、角色切换和页面壳。
- `static/js/api.js`：后端 API 封装。
- `static/pages/case-board/`：Case 看板，支持 Case 删除。
- `static/pages/wizard/`：新建 Case、上传资料、预检、范围确认、Step 5 自动运行预审。
- `static/pages/report/`：客户报告页、PDF 下载入口、管理端抽屉。
- `static/pages/admin-kb/`：知识库管理、检索、chunk 查看、导入和清空。
- `static/pages/admin-trace/`：管理端审查轨迹。
- `static/legacy.html`：旧版调试入口。
- `static/print/`：PDF 打印模板。

报告页当前不再展示“审查范围已变更”的黄色提示；即使 Case 内部存在 `range_dirty`，已有报告也按正常报告展示。

## 后端架构

核心模块：

- `backend/app/factory.py`：FastAPI app、静态资源、Case API、知识库 API、PDF 路由。
- `backend/app/chemical_rag.py`：化工 RAG、规则命中、资料预检、Agent 分支、客户报告生成。
- `backend/app/document_parser.py`：上传文件解析和文本提取。
- `backend/app/store.py`：SQLite Case、文档、报告、知识源、chunk 和向量索引存储。
- `backend/app/pdf_render.py`：HTML/PDF 报告渲染。
- `backend/app/chemistry.py`：物质主数据和化学属性辅助。
- `backend/app/settings.py`：配置。

## 主流程

```text
创建 Case
-> 上传单文件或多文件资料包
-> 资料包预检 package_precheck
-> 资料槽位标准化：安全技术说明书 / 配方 / 工艺 / 其他资料
-> 资料解析与字段抽取
-> 资料完整性门禁 document_quality
-> 按 review_scenario + check_types 路由任务
-> RAG 检索与规则召回
-> 多 Agent 分支判断
-> 主审汇总
-> customer_report 客户报告 + technical_trace 管理端证据
-> 写入 SQLite Case / Report
```

资料不足不会直接拒绝上传。系统采用软门禁：允许继续预审，但在 `package_precheck`、`document_quality` 和 `customer_report` 中明确哪些结论可靠、哪些只能复核、哪些必须补件。

## 资料包预检

`package_precheck` 是上传后的第一阶段输出，用于告诉用户系统读懂了什么、缺什么、哪些检查可靠。

每个文件包含：

- `detected_type`: `sds | formula | process | storage_transport | regulatory_certificate | test_report | unknown`
- `readability`: `readable | partially_readable | unreadable`
- `confidence`
- `recognized_fields`
- `missing_fields`
- `user_message`

资料包整体包含：

- `recognized_documents`
- `missing_documents`
- `available_checks`
- `limited_checks`
- `blocked_checks`
- `supplement_actions`
- `overall_status`

扫描件或不可读资料不会被强行当成安全技术说明书，会进入补件或复核路径。

## 检查项

一级场景：

- 市场准入预审
- 替代物料评估
- 供应商资料准入
- 工艺导入风险评估
- 储运与现场安全评估

二级检查项：

- 资料完整性与可审性
- 成分识别与登记号/浓度完整性
- 禁限用物质与红线物质筛查
- 物料相容性与危险组合
- 安全技术说明书关键章节核查
- 工艺条件适配性
- 储存与运输条件核查
- 目标市场法规匹配
- 供应商声明/检测报告一致性
- 人工复核与补件建议

旧的 `document_completeness/material/process/storage/regulatory` 仍兼容接收，并自动映射到新版业务检查项。

## RAG 与规则

系统使用混合召回：

- 向量召回
- keyword 匹配
- 登记号 exact match
- jurisdiction/domain keyword rerank
- 规则包命中

知识库未加载时，上传审查不会无证据放行，会输出复核或补件相关结论。

## 客户报告

`customer_report` 是普通用户主视图，当前结构为 `customer_report.v1`。客户报告只展开不合格、复核和补件事项，合规项只做摘要。

报告展示约束：

- `rule_text` 用业务准入口径，不直接暴露内部规则 ID。
- `user_text` 优先引用用户上传资料原文。
- 常见英文规则标签在展示层映射为中文。
- “执行要求”在 HTML/PDF 中红色强调。
- 管理端证据不进入客户报告正文。

每条问题包含：

- 编号
- 状态
- 严重度
- 问题分类
- 原因
- 规则 ID 和中文规则名
- 业务化规则说明
- 用户原文
- 影响说明
- 整改建议

## PDF 生成

PDF 路由：

```text
GET /api/cases/{case_id}/report.pdf
```

生成顺序：

1. Playwright Chromium 渲染 `static/print/case-report.html`。
2. Playwright 不可用时，调用系统 Chrome/Edge headless。
3. 浏览器不可用时，使用内置文本 PDF fallback。

## 数据与样例

- `data_samples/chemical_knowledge_sources/official_pack_2026_05/`：官方知识源样例。
- `data_samples/chemical_rag_dataset/manifest.json`：合成回归集，当前 26 个 Case。
- `data_samples/chemical_rag_dataset/upload_samples/`：页面演示上传包，当前 14 个文件夹样例。
- `data_samples/chemical_rag_dataset/knowledge/chemical_rules_pack.json`：开发备用规则包。
- `data/`：本地运行数据，不提交。

## 当前适配器

- 存储：SQLite + 本地文件目录。
- 向量库：SQLite 向量索引。
- Embedding：OpenAI-compatible/Qwen 优先，不可用时 hash embedding 降级。
- LLM：可选接入，用于 Agent 解释，不覆盖硬规则。
- PDF：Playwright、系统浏览器、内置 fallback 三层。
- 前端：模块化静态页面，客户端和管理端分层。

## 生产化替换方向

1. SQLite 替换为 PostgreSQL + pgvector，并引入迁移工具。
2. 本地文件替换为 MinIO 或企业对象存储。
3. 同步审查替换为队列 + LangGraph 状态图。
4. 当前 rerank 增强为 dense + sparse + cross-encoder rerank。
5. 文档解析接入专业 PDF/表格/OCR 管线。
6. 人工复核接入用户、角色、权限、审批流和不可变审计日志。
