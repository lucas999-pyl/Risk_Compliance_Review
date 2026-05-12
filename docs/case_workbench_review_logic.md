# 合规预审 Case 工作台处理逻辑

本文档说明项目从导入客户资料包到各子 Agent 审查、主审汇总和客户报告生成的端到端逻辑。当前实现定位为企业合规预审工具：普通用户查看 Case、资料缺口、客户报告和下一步动作；管理端查看 RAG、Agent 分支、rerank、trace 等技术证据。

## 1. 总体流程

```text
创建 Case
-> 上传单文件或多文件资料包
-> 资料包预检 package_precheck
-> 文档槽位标准化 SDS / 配方 / 工艺 / 其他资料
-> 资料解析与字段抽取
-> 资料完整性门禁 document_quality
-> 按 review_scenario + check_types 路由任务
-> RAG 检索与规则召回
-> 物料 / 工艺 / 储运 / 法规 Agent 分支判断
-> 交叉检查与主审汇总
-> customer_report 客户报告 + technical_trace 管理端证据
-> 写入 SQLite Case / Report
```

资料不足不会直接拒绝上传。系统采用软门禁：允许继续预审，但必须在 `package_precheck`、`document_quality` 和 `customer_report` 中明确哪些结论可靠、哪些只能复核、哪些必须补件。

## 2. Case 创建与任务入口

普通用户入口以 Case 为中心。Case 保存标题、审查场景、目标市场、检查项和状态。

- `review_scenario` 表示一级业务场景，例如供应商准入、替代物料、目标市场筛查、工艺导入、储运安全。
- `check_types` 表示二级检查项，例如资料完整性、成分识别、禁限用筛查、相容性、SDS、工艺、储运、法规、供应商声明一致性。
- `review_task` 保留给管理端高级调试，普通用户流程不依赖手写任务。

旧字段 `document_completeness/material/process/storage/regulatory` 会映射到新版业务检查项，保证旧 API 和测试兼容。

## 3. 资料包预检

上传后先执行 `package_precheck`。预检目标不是下结论，而是回答三件事：

1. 系统读懂了哪些文件。
2. 缺少哪些支撑资料或字段。
3. 本次选择的检查项哪些可直接做，哪些受限，哪些需要补件后再做。

每个文件会输出：

- `filename`
- `detected_type`: `sds | formula | process | storage_transport | regulatory_certificate | test_report | unknown`
- `readability`: `readable | partially_readable | unreadable`
- `confidence`
- `recognized_fields`
- `missing_fields`
- `user_message`

资料包整体会输出：

- `overall_status`: `ready | partial | needs_supplement | unreadable`
- `recognized_documents`
- `missing_documents`
- `available_checks`
- `limited_checks`
- `blocked_checks`
- `supplement_actions`

未知文件不会被强行当作 SDS。扫描 PDF 暂不做 OCR，进入 `unreadable` 或补件路径。

## 4. 文档标准化与字段抽取

预检后，系统把可用资料映射到审查链路需要的槽位：

- SDS 槽位：章节、供应商、修订日期、CAS、GHS、UN 编号等。
- 配方槽位：成分名称、CAS、EC、浓度区间、保密或未知成分。
- 工艺槽位：温度、压力、关键步骤、设备、储存条件、运输信息。
- 其他资料：供应商声明、检测报告、储运说明、未知参考资料。

字段抽取优先使用确定性解析函数。字段缺失、文本不可读、资料类型不清楚会进入 `document_quality` 和补件动作，而不是伪造合格结论。

## 5. 资料完整性门禁

资料完整性不是普通 Agent 分支优先展示，而是所有审查前的门禁。当前确定性门禁检查：

- SDS 16 章节
- 供应商与修订日期
- CAS 与浓度
- 工艺温度、压力、关键步骤
- 储存条件、运输信息
- 资料包是否包含支撑所选检查项的文档类型

门禁输出进入：

- `review_workbench.document_quality`
- `review_workbench.supplement_actions`
- `customer_report.issue_groups` 中的资料完整性问题
- 最终 `verdict`，资料关键缺口会优先映射为 `needs_supplement`

规则函数能稳定判断的字段、章节、硬性缺口都不上 LLM。后续如果要判断字段存在但内容不足、跨文件矛盾、供应商声明和检测报告冲突，再进入 LLM/Agent 语义复核。

## 6. RAG 与规则召回

任务路由后，系统按 Agent 生成 query，并执行混合检索：

- 向量召回
- keyword 匹配
- CAS exact match
- jurisdiction / domain keyword 规则 rerank

召回结果只作为证据候选。客户报告不直接展示 chunk、rerank 分数或 trace；这些内容进入管理端 `retrieval`、`agent_branches` 和 `technical_trace`。

知识库未加载时，系统不会无证据放行，会输出 `needs_review` 或补件/复核相关提示。

## 7. 子 Agent 责任边界

### 资料完整性

资料完整性以函数门禁为主。它负责识别可读性、文件类型、核心字段、缺失资料和补件动作。

输入：上传资料包、解析字段、用户选择的检查项。

输出：`package_precheck`、`document_quality`、`supplement_actions`。

### 物料 Agent

物料 Agent 负责成分与组合关系，不负责判断资料是否齐全。

处理范式：

```text
提取物料/组分
-> 标准化 CAS 与浓度
-> 两两组合和企业红线匹配
-> 命中规则或法规证据
-> 回到用户资料原文确认共存关系
-> 输出合规 / 复核 / 不合规
```

典型问题：未知 CAS、缺浓度、企业禁用物质、可燃物与氧化剂共存。

### 工艺 Agent

工艺 Agent 处理工艺条件是否会放大物料风险。

处理逻辑：

```text
抽取温度、压力、关键步骤和设备
-> 识别同釜混配、加热、加压、投料顺序等上下文
-> 与物料危险属性和禁忌组合交叉
-> 判断工艺条件是否适配
-> 输出工艺复核或整改建议
```

能函数化的缺温度、缺压力、缺关键步骤由门禁处理；需要上下文判断的高温氧化剂、同釜混配和工艺矛盾由 Agent 处理。

### 储运 Agent

储运 Agent 处理储存、隔离、运输与现场安全条件。

处理逻辑：

```text
抽取储存条件、储存类别、运输信息、UN 编号
-> 与物料危险属性、相容性矩阵和法规证据比对
-> 判断隔离、防火、防爆、通风、运输分类是否充分
-> 输出储运不合格、复核或补件建议
```

典型问题：可燃液体缺防火通风说明、氧化剂与还原剂同储、运输 UN 信息不一致。

### 法规 Agent

法规 Agent 按目标市场和 CAS 执行初筛。

处理逻辑：

```text
读取 target_markets
-> 标准化 CAS / EC / 物质名称
-> 检索对应法规和企业规则
-> 判断危化品目录、SVHC、TSCA、红线物质等命中情况
-> 输出目标市场风险和证据版本
```

法规 Agent 的结论依赖知识库版本和来源授权。客户报告展示规则编号、规则原文和影响说明；管理端保留来源 URL、版本、chunk 和 rerank 信息。

## 8. 主审汇总

主审汇总不是简单投票，而是按保守优先级合成：

```text
资料不可读或关键资料缺失 -> needs_supplement
硬性红线或不相容禁忌命中 -> not_approved
知识库不足、资料不足、上下文不确定 -> needs_review
无不合格、无复核、资料可支撑 -> pass
```

Case 状态映射：

- `pass` -> `ready_for_next_step`
- `needs_supplement` -> `needs_supplement`
- `needs_review` -> `needs_review`
- `not_approved` -> `not_approved`
- 未运行 -> `draft`

## 9. 客户报告结构

`customer_report` 是普通用户主视图，采用稳定 schema：

- `schema_version`
- `report_metadata`
- `case_profile`
- `verdict`
- `verdict_label`
- `executive_summary`
- `review_scope`
- `issue_groups`
- `supplement_actions`
- `next_actions`
- `evidence_policy`
- `limitations`
- `technical_reference`
- `disclaimer`

每条问题保留兼容字段和结构化字段：

- `id` / `issue_id`
- `status` / `status_label`
- `severity`
- `category` / `category_label`
- `reason`
- `rule_id` / `rule_text` / `rule`
- `user_text` / `source`
- `impact`
- `recommendation`
- `requires_human_review`

客户报告只展开不合格、复核和补件事项。合规项只做汇总，不列出技术明细。

## 10. 管理端技术输出

以下内容不进入客户报告主视图，仅用于管理端调试、审计和追溯：

- `review_task`
- `task_decomposition`
- `rag_queries`
- `retrieval.chunks`
- `rule_hits`
- `agent_branches`
- `chief_synthesis`
- `trace.nodes`
- `technical_trace`

这种分层保证客户看到的是可执行整改报告，内部人员仍能追踪每个规则命中、证据来源和 Agent 分支判断。
