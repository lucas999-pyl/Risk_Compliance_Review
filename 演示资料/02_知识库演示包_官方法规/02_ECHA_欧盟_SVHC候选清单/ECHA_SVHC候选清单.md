# ECHA Candidate List / SVHC 审查源文档摘要

source_url: https://www.echa.europa.eu/en/candidate-list-table
jurisdiction: EU
source_type: official_registry_summary
source_origin: official
quality_tier: official
document_role: restricted_substance_screening
version: candidate-list-2026-01-demo-reference
effective_date: 2026-01-01
retrieved_at: 2026-05-09
license_note: Public ECHA Candidate List page summarized for demo retrieval. Verify current Candidate List, substance entries and legal obligations directly with ECHA before business use.

## 1. 业务适用范围

ECHA Candidate List 是欧盟 REACH 体系下高度关注物质（SVHC）筛查的重要官方入口。供应商物料准入预审中，SVHC 筛查不能只做名称匹配，还需要结合 CAS、EC、浓度、材料边界、用途、是否进入物品、客户市场和供应链披露要求。

本源文档用于 Demo RAG 检索，重点服务以下问题：

- 上传配方中 CAS 是否可能命中 SVHC 信号。
- 双酚 A 等演示物质是否需要 REACH/SVHC 人工复核。
- 浓度缺失、保密成分或未知 CAS 是否阻断 EU 初筛。
- 未命中时是否可以表达“当前上传知识包未召回命中证据”，而不是声称最终合规。

## 2. 审查控制点

控制点 svhc_cas_match：
优先使用 CAS/EC 精确匹配，其次使用英文名、中文名和别名匹配。名称匹配存在误报风险，必须保留原始字段和匹配依据。

控制点 svhc_concentration_threshold：
SVHC 初筛需要浓度或浓度范围。若浓度缺失，系统不应输出合规，而应要求供应商补充浓度、保密成分声明或法规符合性声明。

控制点 article_mixture_boundary：
混合物、物品、部件和最终产品的合规义务不同。电子零部件清洗剂场景需确认清洗剂是否残留、是否成为物品的一部分，以及客户要求的披露边界。

控制点 source_version_traceability：
SVHC 结论必须引用 Candidate List 来源、版本或检索日期。若知识库未加载或检索不到 ECHA 证据，应进入复核。

## 3. 可检索规则化条款

规则 svhc_threshold_match：
若上传资料显示某成分在演示知识库中作为 SVHC 信号，且浓度达到或超过 0.1% w/w，应输出 `复核`，并要求法规人员确认披露、通报、限制和客户沟通义务。

规则 bisphenol_a_svhc_review：
双酚 A CAS 80-05-7 在本演示包中作为 SVHC 筛查信号。若配方或 SDS 中检出且浓度达到或超过 0.1%，不得自动放行 EU-facing 用途。

规则 svhc_unknown_cas_review：
未知 CAS、保密成分、缺 CAS、缺浓度或无法确认 EC 号时，输出 `复核`。建议动作：要求供应商补充全成分声明、SVHC 声明、RoHS/REACH 符合性声明或第三方检测报告。

规则 svhc_no_hit_with_evidence：
当全部 CAS 已抽取、浓度可用、知识库已上传，并且 RAG 未召回 SVHC 命中证据时，可以表达“当前知识包未发现 SVHC 命中信号”。必须同时展示知识包 `version`、`retrieved_at` 和 source_url，避免被理解为最终法律结论。

规则 svhc_name_only_match_review：
若仅通过商品名、中文别名或模糊名称匹配到候选物质，输出 `复核`。建议人工确认 CAS/EC 后再判断。

## 4. RAG 检索关键词

ECHA Candidate List, SVHC, REACH, Article 33, Article 7, 0.1% w/w, CAS 80-05-7, Bisphenol A, Candidate List table, supplier declaration, confidential ingredient, unknown CAS, EU market access.

## 5. 人审边界

SVHC 初筛结果不能替代 REACH 法规判断。真实业务需结合最新 Candidate List、授权/限制清单、用途、物品边界、供应链角色和客户合同要求进行最终确认。

