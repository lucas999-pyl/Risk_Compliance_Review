# 架构说明

## 主流程

系统使用“知识库源文档上传 + 客户级资料包预审”作为主流程。普通用户不需要手写审查任务，而是提交一个审查项目，选择审查场景和固定检查项：

1. 上传知识库：上传 `manifest_file` 和多份 `source_files`，包括 OSHA、ECHA、EPA、MEM 和内部禁忌矩阵源文档。
2. 构建知识库：解析源文档，生成 chunk，绑定 source_url、version、effective_date、retrieved_at、document_role，并写入 SQLite 向量索引。
3. 提交审查项目：选择 `review_scenario`、`check_types`、`target_markets`，上传一个或多个资料文件。
4. 资料包软门禁预检：系统先识别每个文件的资料类型、可读性、已识别字段和缺失字段；未知文件不会被强行归为 SDS。
5. 资料包标准化：系统把资料包中可信文件映射到 SDS、配方表、工艺说明槽位；缺失槽位进入补件判断。
6. 资料解析：抽取 SDS 章节、CAS/EC、浓度、GHS H/P、UN 编号、供应商、修订日期、温度、压力、储存条件。
7. 资料完整性预检：用确定性规则计算完整性评分、阻断性缺口和补件动作。
8. 任务路由：按业务化 `check_types` 只拆解用户选择的资料可审性、成分识别、禁限用、相容性、SDS、工艺、储运、法规、声明一致性和复核建议子任务。
8. RAG 检索：执行向量召回、keyword/CAS exact match 和规则 Rerank，保留 TopK 证据。
9. 多 Agent 判断：各 Agent 基于对应 query、召回证据和规则输出三值判断。
10. 输出分层：普通用户查看 `customer_report`；管理端查看 `technical_trace`、RAG、Agent 分支和 trace。

## 核心契约

上传审查主接口：

```text
POST /chemical/upload-review
```

普通用户字段：

- `review_scenario`
- `check_types`
- `target_markets`
- `documents`，可上传单文件或多文件资料包

兼容/管理端字段：

- `review_task`
- `sds_file`
- `formula_file`
- `process_file`

上传审查主响应包含：

- `review_scenario`
- `check_types`
- `customer_report`
- `package_precheck`
- `review_workbench.document_quality`
- `review_workbench.supplement_actions`
- `review_workbench.risk_items`
- `technical_trace`
- `task_decomposition`
- `rag_queries`
- `agent_branches`
- `retrieval.chunks`
- `rule_hits`
- `trace.nodes`

## 资料包预检

`package_precheck` 是上传后的第一阶段输出，用于告诉用户系统读懂了什么、缺什么、哪些检查可靠。它采用软门禁：除非没有上传文件或文件完全不可读，否则允许继续初筛，但会把受限范围写清楚。

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
- `overall_status`: `ready | partial | needs_supplement | unreadable`

## 检查项

一级场景包括供应商准入预审、替代物料评估、目标市场合规筛查、工艺导入风险评估、储运与现场安全评估。系统按场景默认勾选推荐检查项，用户可手动调整。

二级检查项包括：

- 资料完整性与可审性
- 成分识别与 CAS/浓度完整性
- 禁限用物质与红线物质筛查
- 物料相容性与危险组合
- SDS 关键章节核查
- 工艺条件适配性
- 储存与运输条件核查
- 目标市场法规匹配
- 供应商声明/检测报告一致性
- 人工复核与补件建议

旧的 `document_completeness/material/process/storage/regulatory` 仍兼容接收，并自动映射到新版业务检查项。

## 客户报告

`customer_report` 是普通用户主视图，只展示不合格、复核和补件事项。合规项不展开为技术列表。报告先说明 `review_scope`：资料包是否足以支撑本次审查、哪些检查可直接完成、哪些检查受资料缺失影响、哪些需要补件。

当前客户报告采用 `customer_report.v1` 稳定结构，便于前端、审批流和审计系统消费。顶层包含：

- `report_metadata`：报告类型、Case ID、运行 ID、生成时间、语言。
- `case_profile`：Case 标题、审查场景、目标市场、所选检查项。
- `executive_summary`：结论、摘要、问题数量、补件数量。
- `review_scope`：资料包状态、可完成检查、受限检查、阻断检查、缺失资料。
- `issue_groups`：按资料完整性、物料、工艺、储运、法规等维度分组。
- `supplement_actions`、`next_actions`、`limitations`。
- `evidence_policy` 与 `technical_reference`：说明客户报告与管理端技术证据的边界。

每条问题包含：

- 编号
- 状态
- 严重度
- 问题分类
- 原因
- 规则编号
- 规则原文
- 用户原文
- 影响说明
- 整改建议

问题按资料完整性、物料、工艺、储运、法规分组。RAG chunk、rerank、agent 分支、trace 节点只进入管理端技术信息。

更完整的端到端处理逻辑见 `docs/case_workbench_review_logic.md`。

## 资料完整性策略

资料完整性分为两层：

- 确定性预检：文件类型、SDS 16 章节、供应商、修订日期、CAS、浓度、工艺温度、压力、关键步骤和储存条件。
- 语义充分性复核：字段存在但内容不足、跨文件矛盾、资料无法支撑所选审查目标时，保留 LLM/Agent 辅助判断空间。

当前实现已把确定性预检作为 Agent 前置门禁，并通过 `document_quality`、`supplement_actions` 和 `customer_report` 影响最终输出。

## 保守策略

未上传知识库时，上传审查必须输出 `复核`，原因是“知识库未加载，不能形成证据充分的预审结论”。内置评测集仅用于回归验证，不作为上传审查结论来源。

## 当前适配器

- 存储：SQLite + 本地文件目录。
- 向量库：SQLite 向量索引。
- Embedding：优先 OpenAI-compatible/Qwen；不可用时 hash embedding 降级。
- LLM：可接入 Qwen3.6-plus，用于 Agent 解释，不覆盖硬规则。
- PDF：仅支持文本型 PDF；扫描件进入复核。
- 前端：静态工作台，普通用户端和管理端调试信息先在同一页面内分层。

## 生产化替换方向

1. SQLite 替换为 PostgreSQL + pgvector，并引入迁移工具。
2. 本地文件替换为 MinIO 或企业对象存储。
3. 同步工作流替换为队列 + LangGraph 状态图。
4. 当前 rules rerank 增强为 dense + sparse + cross-encoder rerank。
5. 文档解析接入专业 PDF/表格/OCR 管线。
6. 人工复核接入用户、角色、权限、审批流和不可变审计日志。
