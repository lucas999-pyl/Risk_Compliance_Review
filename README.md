# 化工合规预审 Case 工作台

这是一个面向化工物料、供应商资料包和目标市场准入的 AI 辅助合规预审工具。项目主形态是 **Case 工作台**：用户创建审查 Case、上传单文件或多文件资料包，系统先做资料包预检，再按业务检查项运行 RAG/规则/Agent 审查，最终输出客户可读的结构化预审报告。

系统定位为企业内部预审和补件辅助工具，不构成最终法律、法规或 EHS 审批意见。

## 核心能力

- Case 工作台：创建草稿 Case、上传资料包、查看预检、运行预审、保存最近报告。
- 资料包预检：识别 SDS、配方、工艺、储运、声明、检测报告和未知资料，说明系统读懂了什么、缺什么、哪些检查可靠。
- 业务检查项：支持供应商准入、替代物料、目标市场筛查、工艺导入、储运安全等场景和固定检查项。
- RAG 与规则：支持 keyword/CAS exact match、向量召回、规则 rerank、证据链和知识库版本信息。
- 多 Agent 审查：按资料完整性、物料、工艺、储运、法规分支分析，并由主审汇总最终预审结论。
- 演示 Case 模板：工作台内置 18 个可一键载入的演示资料包，覆盖合规、补件、复核和不建议准入场景。
- 客户报告：输出 `pass | needs_review | not_approved | needs_supplement`，只展示不合格、复核和补件事项，并支持 HTML、PDF、JSON 下载。
- 管理端证据：保留 review_task、TopK、RAG chunks、rerank、Agent 分支和 trace，供内部排错和审计。

## 技术栈

- Python 3.11+
- FastAPI / Uvicorn
- Pydantic / pydantic-settings
- SQLite 本地存储
- SQLite 本地向量索引
- pytest
- 可选：OpenAI-compatible embedding/LLM、Langfuse、LangGraph、LiteLLM

## 快速启动

安装依赖：

```powershell
python -m pip install -e ".[dev]"
```

如果需要下载正式 PDF 报告，安装报告可选依赖和浏览器运行时：

```powershell
python -m pip install -e ".[dev,reports]"
python -m playwright install chromium
```

未安装 Playwright 或 Chromium 时，HTML/JSON 报告仍可使用，PDF 接口会返回明确的 503 降级提示。

启动服务：

```powershell
uvicorn app.main:app --app-dir backend --reload --port 8888
```

打开工作台：

```text
http://127.0.0.1:8888/
```

## 配置

复制 `.env.example` 为 `.env`，按需配置模型和本地路径：

```powershell
Copy-Item .env.example .env
```

`.env` 包含本机密钥和运行路径，已被 `.gitignore` 排除，不应提交到 GitHub。

## 验证

```powershell
python -m pytest
python -m compileall backend/app
```

## 主要流程

```text
创建 Case
-> 上传资料包
-> package_precheck 资料包预检
-> SDS / 配方 / 工艺 / 其他资料槽位标准化
-> document_quality 资料完整性门禁
-> review_scenario + check_types 任务路由
-> RAG 检索与规则召回
-> 物料 / 工艺 / 储运 / 法规 Agent 分支审查
-> 主审汇总
-> customer_report 客户报告 + technical_trace 管理端证据
-> 写入 SQLite Case / Report
```

## 核心操作路径

1. 启动服务后打开 `http://127.0.0.1:8888/`。
2. 在“客户预审”视图创建 Case，填写案件标题、审查场景和目标市场。
3. 上传客户资料包。资料包可以是单文件或多文件，系统会先执行 `package_precheck`，识别文件类型、可读性、已识别字段和缺失资料。
4. 查看资料包预检结果，确认哪些检查可直接执行、哪些受资料缺失影响、哪些需要供应商补件。
5. 选择或调整固定检查项，运行预审。
6. 在客户报告中查看结论、资料支撑范围、不合格项、复核项、补件清单和下一步动作。
7. 需要排错或审计时，进入管理端查看 review_task、TopK、RAG chunks、Agent 分支、rerank 和 trace。
8. 演示时可以使用页面中的“演示 Case 模板”快速载入样例资料包；真实客户资料包上传入口与演示模板分开。

## 客户报告结构

`customer_report` 是普通用户主视图，当前 schema 为 `customer_report.v1`，包含：

- `report_metadata`：报告类型、Case ID、运行 ID、生成时间、语言。
- `case_profile`：Case 标题、审查场景、目标市场、所选检查项。
- `executive_summary`：结论、摘要、问题数量、补件数量。
- `review_scope`：资料包状态、可完成检查、受限检查、阻断检查、缺失资料。
- `issue_groups`：按资料完整性、物料、工艺、储运、法规等维度分组的问题。
- `supplement_actions` / `next_actions`：补件清单和下一步动作。
- `evidence_policy` / `technical_reference`：说明客户报告与管理端技术证据的边界。

每条问题包含编号、状态、严重度、分类、原因、规则编号、规则原文、用户资料原文/识别结果、影响说明、整改或补件建议。

客户报告下载接口复用同一份 `customer_report.v1`：HTML 是在线预览和 PDF 输入模板，PDF 由 Playwright 服务端渲染生成，JSON 用于系统集成。报告正文不包含 `agent_branches`、`retrieval`、`trace`、RAG chunks 或 rerank 分数；这些内部证据仍保留在管理端。

## 关键 API

- `GET /chemical/demo-cases`
- `GET /chemical/cases`
- `POST /chemical/cases`
- `DELETE /chemical/cases`
- `GET /chemical/cases/{case_id}`
- `POST /chemical/cases/{case_id}/documents`
- `POST /chemical/cases/{case_id}/run-review`
- `GET /chemical/cases/{case_id}/report.json`
- `GET /chemical/cases/{case_id}/report.html`
- `GET /chemical/cases/{case_id}/report.pdf`
- `POST /chemical/upload-review`
- `POST /chemical/knowledge/upload-pack`
- `GET /chemical/knowledge/status`
- `GET /chemical/knowledge/chunks`
- `POST /chemical/knowledge/search`
- `DELETE /chemical/knowledge`
- `GET /chemical/evaluation`

## 数据边界

- `data_samples/chemical_knowledge_sources/official_pack_2026_05/`：知识库源文档样例，用于构建可追溯 chunk 和向量索引。
- `data_samples/chemical_rag_dataset/upload_samples/`：供应商资料包样例，用于本地验证文件上传和预审闭环。
- `data_samples/chemical_rag_dataset/knowledge/chemical_rules_pack.json`：开发备用规则包。
- `data_samples/chemical_rag_dataset/manifest.json`：回归评测集，不参与上传审查结论。
- `data/`：本地数据库、对象文件和向量库目录，已被 `.gitignore` 排除。

## 架构文档

- [架构说明](docs/architecture.md)
- [Case 工作台处理逻辑](docs/case_workbench_review_logic.md)
- [企业级合规智能体技术架构方案](docs/企业级合规智能体技术架构方案.md)
