# 应急管理部危险化学品目录（2015版）实施指南审查源文档摘要

source_url: https://www.mem.gov.cn/gk/gwgg/agwzlfl/gfxwj/2015/201509/t20150902_242909.shtml
jurisdiction: CN
source_type: official_catalog_summary
source_origin: official
quality_tier: official
document_role: hazardous_catalog_screening
version: 危险化学品目录-2015-实施指南
effective_date: 2015-09-02
retrieved_at: 2026-05-09
license_note: 公开官方网页摘要，用于演示目录筛查和证据引用；真实业务应核对官方目录原文、后续调整和企业适用场景。

## 1. 业务适用范围

《危险化学品目录（2015版）》及实施指南是中国危险化学品识别和管理的重要官方依据之一。供应商物料准入预审中，目录命中不是简单等于“不合规”，但会触发储存、运输、采购、使用、许可、台账和 EHS 管理要求复核。

本源文档用于 Demo RAG 检索，重点服务以下问题：

- 乙醇、丙酮、过氧化氢等演示物质是否属于危化品目录筛查信号。
- 危化品目录命中后是否需要人工复核储运、使用和许可边界。
- 混合物中危化组分浓度、用途和储存量是否需要进一步确认。
- 未提供 CAS、浓度或 SDS 关键字段时是否阻断 CN 初筛。

## 2. 审查控制点

控制点 hazardous_catalog_cas_match：
优先使用 CAS 精确匹配目录信号。名称匹配、别名匹配或供应商商品名匹配只能作为复核线索。

控制点 hazardous_catalog_mixture_review：
混合物是否按危险化学品管理，需要结合成分、浓度、危害分类、用途、包装、储量和地方监管要求。Demo 不输出最终许可判断。

控制点 cn_storage_transport_review：
目录命中物质需要进一步确认储存条件、禁忌物、消防、防爆、通风、运输 UN 编号和包装类别。

控制点 cn_missing_information_review：
缺 CAS、缺浓度、缺 SDS 危害分类、缺储存条件或缺工艺温压时，CN 初筛不得自动放行。

## 3. 可检索规则化条款

规则 hazardous_catalog_match：
如 SDS、配方表或供应商声明中出现乙醇 CAS 64-17-5、丙酮 CAS 67-64-1、过氧化氢 CAS 7722-84-1 等演示目录信号，应输出 `复核`。建议动作：由 EHS/法规人员确认危化目录适用、储运要求、许可证照和企业内部准入条件。

规则 hazardous_catalog_unknown_cas_review：
若供应商未提供 CAS 或以保密成分替代危险物质身份，输出 `复核`。建议动作：要求供应商提供受控披露、危化品目录声明或第三方检测证明。

规则 hazardous_storage_condition_missing：
若存在易燃液体、氧化剂、腐蚀品或未知危险物质，但储存条件、禁忌物、通风、防火、防爆措施缺失，输出 `复核`。

规则 hazardous_transport_un_mismatch：
若 SDS 危险性概述与运输信息不一致，例如显示易燃/氧化危害但未提供 UN 编号、运输名称或包装类别，应输出 `复核`。

规则 cn_no_catalog_demo_match_with_evidence：
当知识库已上传、CAS/浓度完整、CN 证据已召回，且未命中演示目录信号时，可以形成“当前知识包未发现危化目录演示命中”的预审意见，最终仍需人工确认。

## 4. RAG 检索关键词

危险化学品目录 2015版, 实施指南, 应急管理部, 乙醇 CAS 64-17-5, 丙酮 CAS 67-64-1, 过氧化氢 CAS 7722-84-1, 危化品目录命中, 储存条件, UN 编号, 危险货物运输, CN 市场准入。

## 5. 人审边界

危化品目录筛查只是中国合规预审的一部分。真实业务还需要结合最新监管文件、地方要求、储存量、用途、运输方式、企业资质和客户要求进行最终确认。

