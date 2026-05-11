# EPA TSCA Inventory 审查源文档摘要

source_url: https://www.epa.gov/tsca-inventory/how-access-tsca-inventory
jurisdiction: US
source_type: official_inventory_summary
source_origin: official
quality_tier: official
document_role: inventory_screening
version: TSCA-inventory-access-2026-demo-reference
effective_date: 2026-01-01
retrieved_at: 2026-05-09
license_note: Public EPA TSCA Inventory access guidance summarized for demo retrieval. Confirm active/inactive status and regulatory obligations through EPA systems before business use.

## 1. 业务适用范围

EPA TSCA Inventory 是美国化学物质制造、加工和进口合规初筛的重要清单入口。供应商物料准入预审中，TSCA 不应被简化为“命中/未命中”一句话，而应把 CAS、物质身份、是否保密、active/inactive 状态、用途和进口/加工角色纳入复核。

本源文档用于 Demo RAG 检索，重点服务以下问题：

- 配方 CAS 是否可以进入 TSCA Inventory 初筛。
- 未知 CAS 或供应商保密成分是否阻断美国市场初筛。
- TSCA 证据是否具备来源 URL、版本和检索时间。
- 未召回 TSCA 证据时是否应输出复核，而不是自动合规。

## 2. 审查控制点

控制点 tsca_cas_identity：
TSCA 初筛依赖准确物质身份。CAS、CA Index Name、PMN/Accession 信息、保密物质声明不一致时，应进入人工复核。

控制点 tsca_active_inactive：
Inventory 中物质状态、用途限制和申报义务可能影响准入。Demo 不直接判断最终义务，只输出证据支持的初筛信号。

控制点 tsca_confidential_substance：
若供应商以商业秘密形式隐藏 CAS 或仅提供商品名，系统不能完成 TSCA 初筛，应要求供应商提供可验证合规声明。

控制点 tsca_evidence_version：
每条 TSCA 相关 finding 必须引用 EPA source_url、版本或 retrieved_at。知识库未上传或未召回 EPA 证据时，输出 `复核`。

## 3. 可检索规则化条款

规则 tsca_inventory_match：
若上传 CAS 被知识库召回为 TSCA 初筛相关物质，系统可记录“TSCA 证据已召回”，但不得自动给出最终美国市场合规结论。需要法规人员确认 active/inactive、用途、进口角色和任何适用限制。

规则 tsca_unknown_cas_review：
未知 CAS、保密成分、缺 CAS 或名称无法唯一映射时，输出 `复核`。建议动作：要求供应商提交 TSCA 合规声明、完整物质身份或受控保密披露材料。

规则 tsca_no_evidence_review：
若目标市场包含 US，但 RAG 未召回 EPA TSCA 相关证据，输出 `复核`。这代表知识库证据不足，不代表物质不受 TSCA 管辖。

规则 tsca_no_restricted_demo_match_with_evidence：
当 CAS 可识别、知识库已上传、EPA 证据已召回，且未命中演示限制信号时，可以形成“未发现演示限制命中”的预审意见，并保留人工最终确认边界。

## 4. RAG 检索关键词

EPA TSCA Inventory, active inactive, confidential substance, CAS identity, chemical substance import, processing, Inventory access, TSCA compliance statement, unknown CAS, US market entry.

## 5. 人审边界

TSCA 初筛需要使用 EPA 官方系统和企业法规团队确认。Demo 仅展示如何把 TSCA 源文档纳入可审计 RAG 证据链，不输出最终美国法规意见。

