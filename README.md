# 化工合规预审 Case 工作台

这是一个面向化工物料、供应商资料包和目标市场准入的 AI 辅助合规预审工具。当前主形态是模块化 **Case 工作台**：用户创建 Case、上传资料包、完成资料预检和审查范围确认后，系统自动运行预审并输出客户可读的结构化报告。

系统用于企业内部准入预审、资料补件和合规排查辅助，不构成最终法律、法规或环境健康安全审批意见。

## 当前能力

- Case 看板：查看 Case、进入报告、新建 Case、删除 Case。
- Wizard 流程：创建 Case、上传单文件或多文件资料包、资料包预检、确认审查范围、自动运行预审。
- 资料包预检：识别安全技术说明书、配方、工艺、储运、声明、检测报告和未知资料，输出可审范围、缺失资料和补件动作。
- RAG 与规则：支持关键字/登记号精确匹配、向量召回、规则 rerank、证据链和知识库版本信息。
- 多 Agent 审查：按资料完整性、物料、工艺、储运、法规等分支分析，并由主审汇总最终结论。
- 客户报告：输出 `pass | needs_review | not_approved | needs_supplement`，只展示不合格、复核和补件事项。
- PDF 报告：使用 feature 模板样式，接口为 `GET /api/cases/{case_id}/report.pdf`。
- 管理端：提供知识库管理、RAG 检索、chunk 查看、规则命中、Agent 分支和 trace 排查入口。
- 演示数据：回归 manifest 当前包含 26 个合成 Case；页面演示上传包当前包含 14 个文件夹样例。

## 技术栈

- Python 3.11+
- FastAPI / Uvicorn
- Pydantic / pydantic-settings
- SQLite 本地存储
- SQLite 本地向量索引
- pytest
- 可选：OpenAI-compatible embedding/LLM、Langfuse、LangGraph、LiteLLM、Playwright

## 快速启动

安装依赖：

```powershell
python -m pip install -e ".[dev]"
```

如需启用 Playwright PDF 渲染：

```powershell
python -m pip install -e ".[dev,reports]"
python -m playwright install chromium
```

启动服务：

```powershell
uvicorn app.main:app --app-dir backend --reload --port 8888
```

打开：

```text
http://127.0.0.1:8888/
```

旧版调试入口保留在：

```text
http://127.0.0.1:8888/legacy
```

## 配置

复制 `.env.example` 为 `.env`：

```powershell
Copy-Item .env.example .env
```

`.env`、`data/`、`logs/`、`.venv/` 等为本地运行内容，不提交到 GitHub。

## 验证

```powershell
python -m compileall backend/app
python -m pytest backend/tests -q
```

## 前端结构

当前前端是静态模块化页面：

```text
backend/app/static/index.html
backend/app/static/js/
backend/app/static/css/
backend/app/static/pages/case-board/
backend/app/static/pages/wizard/
backend/app/static/pages/report/
backend/app/static/pages/admin-kb/
backend/app/static/pages/admin-trace/
backend/app/static/print/
```

报告页不再显示“审查范围已变更”的黄色重跑提示；只要已有报告，就按正常报告展示。Step 4 点击“下一步 · 运行预审”后会直接进入 Step 5 并自动运行预审。

## 主要流程

```text
创建 Case
-> 上传资料包
-> package_precheck 资料包预检
-> 安全技术说明书 / 配方 / 工艺 / 其他资料槽位标准化
-> document_quality 资料完整性门禁
-> review_scenario + check_types 任务路由
-> RAG 检索与规则召回
-> 物料 / 工艺 / 储运 / 法规 Agent 分支审查
-> 主审汇总
-> customer_report 客户报告 + technical_trace 管理端证据
-> 写入 SQLite Case / Report
```

## 报告与 PDF

客户报告采用 `customer_report.v1`，核心字段包括：

- `report_metadata`
- `case_profile`
- `executive_summary`
- `review_scope`
- `issue_groups`
- `supplement_actions`
- `next_actions`
- `evidence_policy`
- `technical_reference`

报告展示策略：

- 客户报告只展示不合格、复核和补件事项。
- “违反规则”使用业务准入口径，按“准入要求 / 执行要求”展示。
- “执行要求”在 HTML 和 PDF 中以红色强调。
- 规则 ID 和常见英文标签在客户展示层映射为中文。
- `user_text` 优先引用用户上传资料原文，不用泛化描述替代。

PDF 生成策略：

1. 优先使用 Playwright Chromium 渲染 `backend/app/static/print/` 模板。
2. Playwright 不可用时，尝试调用系统 Chrome/Edge headless 导出。
3. 浏览器渲染不可用时，使用内置文本 PDF fallback，保证下载接口尽量可用。

## 关键 API

- `GET /chemical/cases`
- `POST /chemical/cases`
- `DELETE /chemical/cases`
- `DELETE /chemical/cases/{case_id}`
- `GET /chemical/cases/{case_id}`
- `POST /chemical/cases/{case_id}/documents`
- `POST /chemical/cases/{case_id}/run-review`
- `POST /chemical/upload-review`
- `GET /api/cases/{case_id}/report.pdf`
- `GET /chemical/knowledge/status`
- `GET /chemical/knowledge/chunks`
- `POST /chemical/knowledge/search`
- `POST /chemical/knowledge/upload-pack`
- `POST /chemical/knowledge/import-demo-pack`
- `DELETE /chemical/knowledge`

## 数据边界

- `data_samples/chemical_knowledge_sources/official_pack_2026_05/`：官方知识源样例和 manifest。
- `data_samples/chemical_rag_dataset/manifest.json`：合成回归集，当前 26 个 Case。
- `data_samples/chemical_rag_dataset/upload_samples/`：页面演示上传包，当前 14 个文件夹样例。
- `data_samples/chemical_rag_dataset/knowledge/chemical_rules_pack.json`：开发备用规则包。
- `data/`：本地数据库、对象文件和向量库目录，已被 `.gitignore` 排除。

## 文档

- [架构说明](docs/architecture.md)
- [Case 工作台处理逻辑](docs/case_workbench_review_logic.md)
- [企业级合规智能体技术架构方案](docs/企业级合规智能体技术架构方案.md)
