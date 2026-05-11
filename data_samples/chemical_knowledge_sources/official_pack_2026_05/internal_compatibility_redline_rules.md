# 企业化工物料准入内部禁忌与红线规则

source_url: internal://chemical-compliance/policies/material-admission-redline
jurisdiction: GLOBAL
source_type: internal_policy
source_origin: internal
quality_tier: internal_controlled
document_role: enterprise_rule_screening
version: internal-demo-2026-05
effective_date: 2026-05-01
retrieved_at: 2026-05-09
license_note: 合成企业内部演示规则。生产环境应由企业 EHS、法规、仓储、工艺安全和采购负责人审批后导入。

## 1. 规则定位

本文件不是官方法规，不伪装成法规来源。它代表企业内部准入控制规则，用于把法规之外的工艺安全、仓储兼容、供应商红线和客户要求纳入预审。

企业内部规则应具备：

- 规则编号和版本。
- 适用范围和例外条件。
- 维护人和审批人。
- 生效日期和失效策略。
- 命中后的建议动作。

## 2. 物质禁忌矩阵

规则 incompatibility_oxidizer_flammable：
乙醇 CAS 64-17-5、丙酮 CAS 67-64-1 等可燃液体，不得与过氧化氢 CAS 7722-84-1 等氧化剂按同一混配单元、同釜、同槽、同罐或同一储存兼容单元处理。若上传资料显示计划混配或同储，输出 `不合规`。

规则 incompatibility_hypochlorite_acid：
次氯酸钠 CAS 7681-52-9 与盐酸 CAS 7647-01-0 或其他酸类同槽、同罐或同储可能释放氯气，输出 `不合规`。

规则 incompatibility_acid_base_uncontrolled：
强酸和强碱在无控制工艺条件、无热释放评估、无通风和应急措施时不得作为新供应商物料自动放行，输出 `复核`。

## 3. 企业红线

规则 enterprise_redline_benzene：
苯 CAS 71-43-2 在本演示企业红线中禁止作为新供应商清洗剂或常规工艺助剂准入，命中时输出 `不合规`。

规则 enterprise_redline_unknown_high_risk：
未知 CAS、保密成分或无法披露浓度的高风险物料不得自动放行，输出 `复核`。

## 4. 工艺和储运补件规则

规则 process_parameters_missing：
缺少工艺温度、压力或关键步骤时，物料不得自动放行，应输出 `复核` 并要求供应商或工艺部门补件。

规则 formula_components_missing：
配方表或 SDS 未提供 CAS、浓度、保密成分合规声明时，输出 `复核`。

规则 storage_condition_missing：
可燃、氧化、腐蚀或未知危害物料缺少储存条件、防火隔离、通风、防爆或禁忌物说明时，输出 `复核`。

规则 source_backed_no_restricted_demo_match：
只有当上传知识库已加载、资料完整、物质可识别、未命中官方筛查信号和内部红线时，系统才可以输出 `合规` 预审建议；最终仍需人工确认。

## 5. RAG 检索关键词

可燃液体, 氧化剂, 乙醇, 过氧化氢, 丙酮, 次氯酸钠, 盐酸, 禁忌组合, 同釜混配, 同槽使用, 储存兼容, 企业红线, 苯, 工艺温度, 工艺压力, 补件。

