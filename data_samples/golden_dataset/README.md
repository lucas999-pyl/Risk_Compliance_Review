# 黄金测试数据集 v1

本目录包含化工材料合规预审 MVP 使用的合成测试数据。

这套数据用于回归测试、演示、提示词评估，以及后续 RAG/Agent 打分。它不是法律或法规参考资料。

## 内容

- `manifest.json` 描述每个案件、预期审查路径和预期 finding 类别。
- `knowledge/demo_regulatory_pack.json` 包含 CN/EU/US 三法域的合成来源支撑知识片段。
- `documents/*.txt` 包含 SDS-like 或供应商提交资料文本夹具。

## 使用方式

- 通过 `POST /knowledge/sources` 和 `POST /knowledge/ingest` 加载 `demo_regulatory_pack.json`。
- 通过 `POST /cases` 创建 manifest 中的案件。
- 通过 `POST /cases/{id}/documents` 上传对应资料。
- 运行 `POST /cases/{id}/run-review`。
- 将输出 finding 的 `jurisdiction`、`issue_type`、`severity` 和 `requires_human_review` 与 `expected_findings` 对比。

所有案件均为合成数据。名称、供应商、配方和法规摘录都是为软件测试虚构的。
