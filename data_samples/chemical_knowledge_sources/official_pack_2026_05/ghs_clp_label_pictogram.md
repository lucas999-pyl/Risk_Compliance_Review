# GHS / CLP / GB 30000.2 标签与象形图审查源文档摘要

source_url: https://unece.org/transport/dangerous-goods/ghs-rev10-2023
jurisdiction: GLOBAL / EU / CN
source_type: official_standard_summary
source_origin: official
quality_tier: official
document_role: ghs_label_screening
version: GHS-Rev10-2023 / CLP-EC-1272-2008 / GB-30000.2-2013-demo
effective_date: 2023-07-01
retrieved_at: 2026-05-09
license_note: 公开 UN GHS / EU CLP / GB 30000.2 标准摘要，仅供 Demo RAG 检索使用。

## 1. 业务适用范围

涂料 / 油墨 / 化工中间体出厂标签与 SDS 第 2、15 章应遵循 GHS 全球化学品统一分类与标签制度。本源文档用于 Demo RAG 检索：

- SDS 是否提供完整 GHS 分类、信号词、象形图、H 语句、P 语句。
- CN 市场标签是否满足 GB 30000.2-2013 / GB 15258-2009。
- EU 市场标签是否满足 CLP Regulation (EC) No 1272/2008。
- 标签字段缺失或不一致时是否进入复核。

## 2. GHS 象形图速查

| 编号 | 中文名称 | 适用类别（示例） |
| ---- | -------- | ---------------- |
| GHS01 | 爆炸物 | 有机过氧化物 A 型、B 型 |
| GHS02 | 火焰（易燃） | 易燃液体 1–3 类（乙醇、丙酮、甲苯、乙酸乙酯） |
| GHS03 | 圆圈上火焰（氧化） | 氧化性液体 / 固体（过氧化氢、过硫酸铵、过氧化苯甲酰） |
| GHS04 | 气瓶 | 加压气体 |
| GHS05 | 腐蚀 | 皮肤腐蚀 1A/1B/1C（盐酸、氢氧化钠） |
| GHS06 | 骷髅与十字骨 | 急性毒性 1–3 类 |
| GHS07 | 感叹号 | 急性毒性 4 类 / 皮肤刺激 / 眼刺激 |
| GHS08 | 健康危害 | 致癌物 1A/1B/2、生殖毒性、特异性靶器官毒性（苯、双酚 A） |
| GHS09 | 环境危害 | 水生急性 / 慢性 1 类 |

## 3. 标签必备字段

按 CLP / GB 30000.2，标签必须包含：

1. 产品标识（产品名称、UFI 唯一配方标识符）
2. 信号词：危险 / 警告（Danger / Warning）
3. 象形图：GHS01–GHS09 中适用项
4. H 危险性说明（如 H225 高度易燃液体和蒸气）
5. P 防范说明（如 P210 远离热源 / P280 戴防护手套）
6. 供应商信息：名称、地址、电话
7. 补充信息：UFI（EU PCN 编号）、批号、容量

## 4. 可检索规则化条款

规则 ghs_label_pictogram_missing：
若 SDS 第 2 章 / 第 15 章 / 出厂标签未提供完整 GHS 象形图编号、信号词或 H/P 语句，输出 `复核`。建议动作：要求供应商补全标签照片或重新出具 GHS 分类说明。

规则 ghs_signal_word_conflict：
若信号词与象形图不匹配（例如标 GHS02 易燃却写"警告"而非"危险"），输出 `复核`。

规则 ghs_hp_phrase_missing：
若配方含可燃 / 氧化 / 腐蚀 / 急毒组分，但 H 语句或 P 语句缺失，输出 `复核`。

## 5. RAG 检索关键词

GHS 分类, GHS01, GHS02, GHS03, 象形图, 信号词, 危险, 警告, H225, H272, H314, P210, P280, CLP, GB 30000.2, GB 15258, UFI, PCN, hazard pictogram。

## 6. 人审边界

GHS 标签合规初筛只覆盖 SDS / 标签可见字段。出厂前应由合规人员根据最新分类指导文件、客户市场要求和实际成分浓度复核。
