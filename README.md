# 化工合规 RAG 工具 Demo2.6

这是一个围绕化工合规预审场景的技术 Demo。Demo2.6 的主线是“官方知识库源文档上传 + 审查任务驱动的现场资料审查”：先手动上传一组可审计的官方优先知识库源文档，再输入具体审查任务，并上传供应商 SDS、配方表、工艺说明三份资料。系统基于真实上传内容执行资料解析、任务拆解、多 query RAG 检索、Rerank、规则命中、多 Agent 分支分析、主审汇总、证据链和三值判定。

系统定位为 AI 辅助预审工具，不构成最终法律、法规或 EHS 合规意见。

## 当前能力

- FastAPI 后端提供化工 RAG 审查接口：`POST /chemical/upload-review`、`POST /chemical/knowledge/upload-pack`、`GET /chemical/knowledge/chunks`、`POST /chemical/knowledge/search`。
- 前端首页 `/` 默认展示“知识库工作台 + 上传审查工作台”，不再把内置 case 作为主入口。
- 知识库主流程是上传 `manifest_file` 和多份 `source_files`，写入 SQLite 元数据表和本地 SQLite 向量索引。
- 默认官方优先知识源位于 `data_samples/chemical_knowledge_sources/official_pack_2026_05/`，覆盖 OSHA HCS/SDS、ECHA SVHC、EPA TSCA、应急管理部危险化学品目录和内部禁忌矩阵。
- 未加载知识库时，上传审查不会静默使用短规则包放行，而是保守输出 `复核` 并提示“知识库未加载”。
- Query 工作台提供高频问题模板和最近 10 条查询历史，支持一键复用到检索或审查任务。
- “抽取校验”已收敛为“资料完整性与补件判断”，输出完整性评分、阻断性缺口、补件动作，并进入主审复核逻辑。
- `.env` 可配置阿里云百炼 OpenAI-compatible 接口：默认 embedding 模型 `text-embedding-v4`，LLM 模型 `qwen3.6-plus`；不可用时降级到 hash embedding 和规则解释。

## 快速启动

```powershell
python -m pip install -e ".[dev]"
uvicorn app.main:app --app-dir backend --reload --port 8888
```

打开：

```text
http://127.0.0.1:8888/
```

验证：

```powershell
python -m pytest
python -m compileall backend/app
```

## 便携包启动（8080）

如果要复制到其他 Windows 电脑演示，可使用便携启动脚本：

```powershell
start-8080.bat
```

打开：

```text
http://127.0.0.1:8080/
```

生成便携 zip：

```powershell
powershell -ExecutionPolicy Bypass -NoProfile -File scripts/build-portable-package.ps1
```

生成结果位于：

```text
dist/Risk_Compliance_Review_portable_8080.zip
```

便携包会包含本机 `.env`，用于在新电脑继续连接阿里云百炼模型；不会包含数据库、向量库、上传对象、缓存或临时服务日志。由于 `.env` 包含密钥，请只在受控环境分发。详细说明见 `docs/portable-8080-guide.md`。

## 推荐演示顺序

1. 打开 `http://127.0.0.1:8888/`。
2. 在左侧下载官方知识库 `manifest` 和 5 份源文档。
3. 手动选择 `manifest_file` 和所有 `source_files`，点击“上传官方知识库源文档”。
4. 点击“查看知识 Chunk”，展示 source、version、effective_date、retrieved_at、document_role、tokens 和向量状态。
5. 在“高频问题”中选择一个问题，例如“乙醇/过氧化氢禁忌组合”，运行向量检索实验，查看 TopK、keyword、CAS exact match、Rerank 解释。
6. 在“供应商资料包”中选择 A/B/C 任一资料包，或手动选择自己的 SDS、配方表、工艺说明。
7. 修改“审查任务”，例如：`请判断该供应商清洗剂是否可用于电子零部件清洗工艺，并进入 CN/EU 市场。`
8. 点击“上传并运行审查”。接口只读取上传文件和审查任务，不读取评测集 expected verdict。
9. 查看中间区域的三值判定、资料完整性与补件判断、任务拆解和风险项。
10. 展开技术细节，查看多 query RAG 召回、TopK 原始召回、Rerank 后排序、Agent 分支分析、流程回放和 Trace JSON。
11. 点击不同风险项，在右侧查看证据链、建议动作、主审汇总和预审报告摘要。

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

`POST /chemical/knowledge/import-demo-pack` 仍作为开发备用接口保留，但不作为客户演示主入口。

## 数据边界

- `data_samples/chemical_knowledge_sources/official_pack_2026_05/`：官方优先知识库源文档，用于演示可审计知识库上传、chunk 和向量入库。
- `data_samples/chemical_rag_dataset/upload_samples/`：三组可现场手动上传的供应商资料包，用于稳定演示文件上传审查闭环。
- `data_samples/chemical_rag_dataset/knowledge/chemical_rules_pack.json`：短小开发备用规则包，不再作为客户主展示知识库。
- `data_samples/chemical_rag_dataset/manifest.json`：内置回归评测集，不参与现场上传审查结论。

## 技术链路

```text
官方/内部源文档 -> manifest 校验 -> chunk -> embedding -> SQLite 向量索引
审查任务 + 上传 SDS/配方/工艺 -> 字段抽取 -> 资料完整性与补件判断
-> 任务拆解 -> 每个 Agent 生成独立 query
-> vector search + keyword/CAS match -> rules rerank -> evidence chunks
-> 资料完整性/物料/工艺/储运/法规 Agent
-> 交叉质检 -> 主审汇总 -> 合规/复核/不合规 -> 证据链与预审报告摘要
```
