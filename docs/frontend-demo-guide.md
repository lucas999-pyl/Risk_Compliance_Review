# 前端网站演示说明：化工合规 RAG 工具 Demo2.6

Demo2.6 的演示重点是“先上传官方优先知识库，再上传供应商资料包并提交审查任务”。不要从内置 case 开始讲，也不要把短小规则包当成知识库能力展示。主线应让客户看到：知识源文档、chunk、embedding、向量库、query、Rerank、规则、Agent 分支和主审结论之间有真实数据流。

## 1. 启动服务

```powershell
python -m pip install -e ".[dev]"
uvicorn app.main:app --app-dir backend --reload --port 8888
```

浏览器打开：

```text
http://127.0.0.1:8888/
```

## 2. 推荐演示路径

1. 进入首页后先看左侧“知识库工作台”。
2. 下载官方知识库 `manifest` 和 OSHA、ECHA、EPA、MEM、内部禁忌矩阵 5 份源文档。
3. 手动选择 `manifest_file` 和所有 `source_files`。
4. 点击“上传官方知识库源文档”，说明系统会执行源文档解析、chunk 切分、embedding 和向量入库。
5. 点击“查看知识 Chunk”，展示每个 chunk 的来源、法域、版本、生效日期、retrieved_at、document_role、tokens 和 vector_status。
6. 点击“高频问题”模板，例如“乙醇/过氧化氢禁忌组合”，运行检索实验。
7. 展示 Rerank 解释：vector_score、keyword_score、CAS exact match、法域匹配、领域关键词和 rerank_score。
8. 选择“供应商 B：含乙醇/过氧化氢清洗剂资料包”，或手动选择三份外部文件。
9. 查看或修改“审查任务”文本框，例如：

```text
请判断该供应商清洗剂是否可用于电子零部件清洗工艺，并进入 CN/EU 市场。
```

10. 点击“上传并运行审查”，后端调用 `POST /chemical/upload-review`，只读取上传文件和 review_task。
11. 查看中间区域：
    - 三值判定：合规 / 复核 / 不合规
    - 资料完整性与补件判断：完整性评分、阻断性缺口、补件动作
    - 任务拆解：资料完整性、物料、工艺、储运、法规子任务
    - 风险项：每个风险项绑定规则、证据和建议动作
12. 查看右侧：
    - 当前风险证据链
    - 建议动作
    - 主审汇总
    - 预审报告摘要
13. 最后展开“技术细节”，展示多 query RAG 召回、TopK 原始召回、Rerank 后排序、Agent 分支分析、流程回放和 Trace JSON。

## 3. 资料包说明

可现场上传的三组预生成外部资料在：

```text
data_samples/chemical_rag_dataset/upload_samples/
```

| 资料包 | 演示重点 | 说明 |
| --- | --- | --- |
| 供应商 A：`compliant_water_cleaner_*` | 资料完整、未命中红线 | 水 + 氯化钠，适合展示来源证据充分时的预审放行建议 |
| 供应商 B：`incompatible_oxidizer_flammable_*` | 硬性拦截 | 乙醇 + 过氧化氢，上传后命中可燃液体/氧化剂禁忌组合 |
| 供应商 C：`unknown_missing_process_*` | 保守复核 | 未知 CAS 且缺少工艺温度、压力、步骤 |

这些资料包用于稳定演示“手动选择文件上传”的过程。上传接口不读取预设结论。

## 4. 知识库来源

客户演示主入口调用：

```text
POST /chemical/knowledge/upload-pack
```

默认源文件位置：

```text
data_samples/chemical_knowledge_sources/official_pack_2026_05/
```

包含：

- OSHA HCS 2024 SDS / Appendix D 官方摘要
- ECHA Candidate List / SVHC 官方摘要
- EPA TSCA Inventory 官方访问说明摘要
- 应急管理部《危险化学品目录（2015版）》实施指南官方摘要
- 企业内部禁忌矩阵与红线规则，明确标记为 `internal_policy`

开发备用接口 `POST /chemical/knowledge/import-demo-pack` 保留给回归测试和快速开发，不建议在客户演示中使用。

## 5. 对客户的讲解重点

- 这不是 Chatbot：LLM 不直接给最终合规结论。
- 知识库是可审计的：来源、版本、生效日期、URL、retrieved_at、chunk 和向量状态都可查看。
- RAG 是可解释的：TopK 召回和 Rerank 原因可以展开检查。
- RAG 是按任务拆解执行的：每个 Agent 有自己的 query 和召回结果。
- 规则引擎承载确定性判断：禁忌组合、资料缺失、未知 CAS、企业红线由规则控制。
- 资料完整性不是摆设：阻断性缺口会生成补件动作，并进入主审复核。
- 输出是 AI 辅助预审，不构成最终法规、法律或 EHS 合规意见。

## 6. 自动化验证

```powershell
python -m pytest
python -m compileall backend/app
```

