# OSHA HCS 2024 SDS / Appendix D 审查源文档摘要

source_url: https://www.osha.gov/laws-regs/federalregister/2024-05-20
jurisdiction: US
source_type: official_regulation_summary
source_origin: official
quality_tier: official
document_role: sds_completeness
version: HCS-2024-final-rule
effective_date: 2024-07-19
retrieved_at: 2026-05-09
license_note: Public official OSHA source summarized for demo retrieval. Verify against the official Federal Register / OSHA text before business use.

## 1. 业务适用范围

OSHA Hazard Communication Standard (HCS) 是美国工作场所危险化学品分类、标签和安全数据表的重要依据。供应商物料准入预审中，SDS 不是附件，而是后续危害识别、储运兼容、PPE、防火、防泄漏、废弃处置和法规筛查的证据入口。

本源文档用于 Demo RAG 检索，重点服务以下问题：

- SDS 是否具备标准 16 章节结构。
- 供应商、产品标识、推荐用途、修订日期是否完整。
- GHS 分类、H/P 语句、危害图形、UN 编号、闪点、稳定性和反应性信息是否足以支撑审查。
- SDS 缺失、扫描不可解析、字段冲突或修订日期缺失时是否应进入人工复核。

## 2. 标准 SDS 章节控制点

规则 sds_16_sections_required：
SDS 应覆盖 1 至 16 章节。系统抽取时至少记录章节号、章节标题、章节文本片段和解析状态。缺章、章节顺序严重异常、扫描件无法提取文本，均不得自动放行。

建议字段清单：

1. 化学品及企业标识：产品名称、供应商、应急电话、推荐用途。
2. 危险性概述：GHS 分类、危险性说明、预防措施、图形符号。
3. 成分/组成信息：CAS、EC、组分名称、浓度或浓度范围。
4. 急救措施。
5. 消防措施：适用灭火剂、特殊危害、消防人员防护。
6. 泄漏应急处理。
7. 操作处置与储存。
8. 接触控制和个体防护。
9. 理化特性：闪点、沸点、pH、蒸气压、密度、溶解性等。
10. 稳定性和反应性：禁配物、危险反应、分解产物。
11. 毒理学信息。
12. 生态学信息。
13. 废弃处置。
14. 运输信息：UN 编号、运输名称、包装类别。
15. 法规信息。
16. 其他信息：修订日期、版本、免责声明。

## 3. 可检索规则化条款

规则 sds_complete：
当 SDS 16 章节齐全，供应商、修订日期、CAS/浓度、GHS 分类、储存条件、运输信息和法规信息均可抽取时，可作为资料完整性正向证据。该规则本身不等于合规放行，只证明后续审查资料基础较完整。

规则 sds_missing_sections：
若 SDS 缺少关键章节、文件不可解析、章节号无法识别，或文本明显来自图片扫描，输出 `复核`。建议动作：要求供应商补充可复制文本型 SDS 或由人工录入关键字段。

规则 sds_revision_outdated：
若 SDS 修订日期缺失、过旧、与供应商声明不一致，输出 `复核`。建议动作：要求供应商提交当前有效版本并确认适用产品型号。

规则 supplier_identity_missing：
若供应商名称、应急联系方式、产品标识或推荐用途缺失，输出 `复核`。影响范围：责任主体、市场准入、事故响应和采购准入均无法闭环。

规则 ghs_hazard_statement_missing：
若配方或工艺显示可燃、氧化、腐蚀、急毒、环境危害等风险，但 SDS 未给出 GHS 分类、H 语句、P 语句或图形符号，输出 `复核`。建议动作：要求供应商补充分类依据或测试/分类声明。

规则 stability_reactivity_incompatibility：
SDS 第 10 章应提供稳定性、反应性、应避免条件和禁配物。若配方中存在氧化剂、可燃液体、酸、碱、次氯酸盐等高敏组合，而 SDS 第 10 章为空或未披露禁配信息，应进入复核。

规则 transport_information_required_when_hazardous：
当 SDS 显示危险分类、UN 编号或运输危险类别时，应保留运输名称、UN 编号、包装类别和法规说明。若配方/危害显示危险品特征但第 14 章缺失，输出 `复核`。

## 4. RAG 检索关键词

SDS 16 sections, OSHA HCS 2024, Appendix D, safety data sheet, supplier identity, revision date, GHS classification, hazard statements, precautionary statements, Section 10 stability reactivity, Section 14 transport information, UN number, SDS completeness, scanned PDF manual review.

## 5. 人审边界

完整 SDS 不代表最终合规。系统只能输出 AI 辅助预审建议；最终美国市场或工作场所适用性，需要由 EHS/法规人员结合真实用途、暴露场景、州法规和客户要求确认。

