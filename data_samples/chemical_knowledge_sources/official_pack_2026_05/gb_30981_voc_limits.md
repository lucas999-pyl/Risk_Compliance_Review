# GB 30981-2020 / CARB SCAQMD 工业涂料 VOC 限值审查源文档摘要

source_url: https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno=GB30981-2020
jurisdiction: CN / US-CA / EU
source_type: official_standard_summary
source_origin: official
quality_tier: official
document_role: voc_limit_screening
version: GB-30981-2020-with-CARB-Rule-1113-2024-demo
effective_date: 2020-12-01
retrieved_at: 2026-05-09
license_note: 公开标准摘要，用于演示 VOC 限值核查。生产环境应核对 GB 30981-2020 / CARB SCAQMD Rule 1113 当前版本与企业产品类别。

## 1. 业务适用范围

工业防护涂料、木器涂料、汽车涂料、油墨产品在 CN / EU / US 市场销售必须满足挥发性有机物（VOC）限值。本源文档用于 Demo RAG 检索，重点服务以下问题：

- 上传配方中 VOC 总量是否超过 GB 30981-2020 限值。
- 溶剂型 / 水性 / UV 固化体系应使用哪一档限值。
- VOC 字段缺失时是否进入复核或补件流程。
- 客户面向加州市场时是否需要按 CARB SCAQMD Rule 1113 更严限值复核。

## 2. 限值速查（演示用）

| 产品类别 | 单位 | GB 30981-2020 限值 | CARB Rule 1113 限值 |
| -------- | ---- | ------------------ | ------------------- |
| 工业防护涂料 — 溶剂型双组分 | g/L | ≤ 550 | ≤ 340 |
| 工业防护涂料 — 水性双组分 | g/L | ≤ 250 | ≤ 250 |
| 工业防护涂料 — 单组分溶剂型 | g/L | ≤ 500 | ≤ 340 |
| 木器涂料 — 溶剂型底漆 | g/L | ≤ 700 | ≤ 350 |
| 木器涂料 — 水性面漆 | g/L | ≤ 120 | ≤ 250 |
| 印刷油墨 — 溶剂型 | g/kg | ≤ 700 | — |
| 印刷油墨 — 水性 | g/kg | ≤ 100 | — |

注：本表为演示简化版，真实业务应使用 GB 30981 完整附录与 CARB SCAQMD Rule 1113 当前修订版。

## 3. 审查控制点

控制点 voc_value_present：
配方或 SDS 第 9 章应给出 VOC 数值（g/L 或 g/kg）。仅写「低 VOC」「环保配方」不可作为依据。

控制点 voc_unit_consistency：
g/L 与 g/kg 不能混用；密度差异可能导致 30% 偏差。审查应保留单位原文。

控制点 voc_test_method：
GB/T 23985 / ASTM D2369 / ISO 11890-2 为常用 VOC 测定方法。SDS 应注明测试方法。

## 4. 可检索规则化条款

规则 voc_limit_exceeded：
若配方 / SDS 披露 VOC 数值超过对应类别 GB 30981-2020 限值，输出 `不合规`。建议动作：要求供应商提供低 VOC 配方版本或调整销售市场。

规则 voc_value_missing：
若配方或 SDS 未提供 VOC 数值或仅以模糊描述（环保、低 VOC）替代，输出 `needs_supplement`，要求供应商补充 VOC 测试报告。

规则 voc_carb_review：
目标市场包含 US-CA 时，应按 CARB SCAQMD Rule 1113 限值复核（比 GB 30981 更严），输出 `复核` 并提示加州市场专项要求。

## 5. RAG 检索关键词

VOC 限值, GB 30981-2020, CARB SCAQMD Rule 1113, 挥发性有机物, g/L, g/kg, 溶剂型涂料, 水性涂料, 工业防护涂料, 木器涂料, 印刷油墨, ASTM D2369, ISO 11890-2, 加州市场。

## 6. 人审边界

VOC 限值合规初筛不等于最终市场准入。还需结合产品分类、出厂检验、客户合同要求、地方监管文件（如各省 VOC 排放标准）和环保税申报口径。
