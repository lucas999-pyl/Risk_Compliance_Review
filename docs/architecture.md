# 架构说明

## 主流程

系统使用“知识库源文档上传 + 固定检查项驱动的供应商资料包预审”作为主流程：

1. 上传知识库：上传 `manifest_file` 和多份 `source_files`，包括 OSHA、ECHA、EPA、MEM 和内部禁忌矩阵源文档。
2. 构建知识库：解析源文档，生成 chunk，绑定 source_url、version、effective_date、retrieved_at、document_role，并写入 SQLite 向量索引。
3. 选择检查项：用户端勾选 `material / process / storage / regulatory` 标准检查项，不要求用户手写审查任务。
4. 上传供应商资料：上传 SDS、配方表、工艺说明三份 txt/pdf 文件。
5. 函数预检：用确定性规则检查文件齐套、SDS 章节、CAS/浓度、工艺温压、关键步骤和储存条件。
6. 任务拆解：按已选检查项拆成物料、工艺、储运、法规子任务，每个子任务生成独立 RAG query。
7. RAG 检索：执行向量召回、keyword/CAS exact match 和规则 Rerank，保留 TopK 证据。
8. Agent 判断：物料、工艺、储运、法规 Agent 基于对应 query、召回证据和规则输出三值判断。
9. 主审汇总：按规则优先原则输出 `合规 / 复核 / 不合规`。
10. 结构化报告：用户端只展示不合规项和复核项，逐条给出规则原文、用户原文和改进建议。

## 核心契约

上传审查主响应包含：

- `check_types`
- `review_task`
- `task_decomposition`
- `rag_queries`
- `agent_branches`
- `chief_synthesis`
- `review_workbench.precheck`
- `review_workbench.document_quality`
- `review_workbench.supplement_actions`
- `review_workbench.structured_report`
- `review_workbench.risk_items`
- `retrieval.chunks`
- `rule_hits`
- `trace.nodes`

## 决策边界

- 用户端输入是固定检查项 enum，不是自然语言任务描述。
- 资料完整性是函数预检，不进入 LLM Agent 编排。
- Agent 只处理需要上下文确认、组合关系和冲突推理的物料、工艺、储运、法规判断。
- 合规项不进入用户端整改报告；内部 trace、chunk、rerank 和 Agent 细节保留在管理/技术折叠区。

## 保守策略

未上传知识库时，上传审查必须输出 `复核`，原因是“知识库未加载，不能形成证据充分的预审结论”。资料预检出现阻断性缺口时，也必须进入 `复核` 并输出补件动作。内置评测集仅用于回归验证，不作为上传审查结论来源。

## 当前适配器

- 存储：SQLite + 本地文件目录。
- 向量库：SQLite 向量索引。
- Embedding：优先 OpenAI-compatible/Qwen；不可用时 hash embedding 降级。
- LLM：可接入 Qwen3.6-plus，用于 Agent 解释，不覆盖硬规则。
- PDF：仅支持文本型 PDF；扫描件进入复核。
- 前端：静态工作台，用户端入口为上传资料 + 勾选检查项 + 查看结构化报告。

## 生产化替换方向

1. SQLite 替换为 PostgreSQL + pgvector，并引入迁移工具。
2. 本地文件替换为 MinIO 或企业对象存储。
3. 同步工作流替换为队列 + LangGraph 状态图。
4. 当前 rules rerank 增强为 dense + sparse + cross-encoder rerank。
5. 文档解析接入专业 PDF/表格/OCR 管线。
6. 人工复核接入用户、角色、权限、审批流和不可变审计日志。
