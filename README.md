# 化工合规 RAG 审查系统

这是一个面向化工物料合规预审的 RAG 审查系统。系统以官方/内部知识库、供应商资料包、任务拆解、多 query 检索、规则命中、多 Agent 分支分析、主审汇总和证据链为核心，输出 `合规 / 复核 / 不合规` 三值判定。

系统定位为 AI 辅助预审工具，不构成最终法律、法规或 EHS 合规意见。

## 核心能力

- FastAPI 后端提供化工 RAG 审查接口。
- 支持上传知识库 `manifest_file` 和多份 `source_files`，生成 chunk 并写入 SQLite 元数据表和本地 SQLite 向量索引。
- 支持上传 SDS、配方表、工艺说明，执行字段抽取、资料完整性判断、任务拆解和证据检索。
- 支持 keyword/CAS exact match、向量召回、规则 rerank 和多 Agent 风险分析。
- 未加载知识库时，上传审查保守输出 `复核`，避免无证据放行。
- `.env` 可配置 OpenAI-compatible embedding/LLM 接口；远程模型不可用时降级到 hash embedding 和规则解释。

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

启动服务：

```powershell
uvicorn app.main:app --app-dir backend --reload --port 8888
```

打开：

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

## 关键 API

- `POST /chemical/knowledge/upload-pack`
- `GET /chemical/query-presets`
- `GET /chemical/knowledge/status`
- `GET /chemical/knowledge/chunks`
- `POST /chemical/knowledge/search`
- `POST /chemical/upload-review`
- `DELETE /chemical/knowledge`
- `GET /chemical/evaluation`
- `POST /chemical/runs`

## 数据边界

- `data_samples/chemical_knowledge_sources/official_pack_2026_05/`：知识库源文档样例，用于构建可追溯 chunk 和向量索引。
- `data_samples/chemical_rag_dataset/upload_samples/`：供应商资料包样例，用于本地验证文件上传审查闭环。
- `data_samples/chemical_rag_dataset/knowledge/chemical_rules_pack.json`：开发备用规则包。
- `data_samples/chemical_rag_dataset/manifest.json`：回归评测集，不参与上传审查结论。
- `data/`：本地数据库、对象文件和向量库目录，已被 `.gitignore` 排除。

## 技术链路

```text
官方/内部源文档 -> manifest 校验 -> chunk -> embedding -> SQLite 向量索引
审查任务 + 上传 SDS/配方/工艺 -> 字段抽取 -> 资料完整性与补件判断
-> 任务拆解 -> 每个 Agent 生成独立 query
-> vector search + keyword/CAS match -> rules rerank -> evidence chunks
-> 资料完整性/物料/工艺/储运/法规 Agent
-> 交叉质检 -> 主审汇总 -> 合规/复核/不合规 -> 证据链与预审报告摘要
```

## 架构文档

- `docs/architecture.md`
- `docs/企业级合规智能体技术架构方案.md`
