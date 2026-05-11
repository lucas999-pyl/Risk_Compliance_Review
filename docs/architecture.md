# 架构说明

## Demo2.6 主流程

当前 Demo 使用“官方知识库源文档上传 + 审查任务驱动的供应商资料包预审”作为主流程：

1. 上传知识库：手动上传 `manifest_file` 和多份 `source_files`，包括 OSHA、ECHA、EPA、MEM 和内部禁忌矩阵源文档。
2. 构建知识库：解析源文档，生成 chunk，绑定 source_url、version、effective_date、retrieved_at、document_role，并写入 SQLite 向量索引。
3. 提交审查任务：用户输入具体业务 query，例如电子零部件清洗剂 CN/EU 准入判断。
4. 上传供应商资料：上传 SDS、配方表、工艺说明三份 txt/pdf 文件。
5. 资料解析：抽取 SDS 章节、CAS/EC、浓度、GHS H/P、UN 编号、供应商、修订日期、温度、压力、储存条件。
6. 资料完整性与补件判断：计算完整性评分，生成阻断性缺口、补件动作和人工复核项。
7. 任务拆解：拆成资料完整性、物料、工艺、储运、法规等子任务，每个子任务生成独立 RAG query。
8. RAG 检索：执行向量召回、keyword/CAS exact match 和规则 Rerank，保留 TopK 证据。
9. 多 Agent 判断：各 Agent 基于对应 query、召回证据和规则输出三值判断。
10. 主审汇总：按规则优先原则输出 `合规 / 复核 / 不合规`，并生成证据链和预审报告摘要。

## 核心契约

上传审查主响应包含：

- `knowledge_pack`
- `review_task`
- `task_decomposition`
- `rag_queries`
- `agent_branches`
- `chief_synthesis`
- `review_workbench.document_quality`
- `review_workbench.supplement_actions`
- `review_workbench.risk_items`
- `retrieval.chunks`
- `rule_hits`
- `trace.nodes`

## 保守策略

未上传知识库时，现场上传审查必须输出 `复核`，原因是“知识库未加载，不能形成证据充分的预审结论”。内置评测集仍可使用受控规则包进行回归评测，但不作为客户主流程。

## 当前适配器

- 存储：SQLite + 本地文件目录。
- 向量库：SQLite 向量索引。
- Embedding：优先 OpenAI-compatible/Qwen；不可用时 hash embedding 降级。
- LLM：可接入 Qwen3.6-plus，用于 Agent 解释，不覆盖硬规则。
- PDF：仅支持文本型 PDF；扫描件进入复核。
- 前端：静态工作台，主入口为官方知识包上传和现场资料上传。

## 生产化替换方向

1. SQLite 替换为 PostgreSQL + pgvector，并引入迁移工具。
2. 本地文件替换为 MinIO 或企业对象存储。
3. 同步工作流替换为队列 + LangGraph 状态图。
4. 当前 rules rerank 增强为 dense + sparse + cross-encoder rerank。
5. 文档解析接入专业 PDF/表格/OCR 管线。
6. 人工复核接入用户、角色、权限、审批流和不可变审计日志。

