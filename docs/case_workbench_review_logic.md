# 合规预审 Case 工作台处理逻辑

本文档说明当前项目从创建 Case、上传客户资料包、运行资料预检、执行 RAG/规则/Agent 审查，到生成客户报告和管理端证据的端到端逻辑。

## 1. 页面流程

当前用户流程以模块化 Wizard 为主：

```text
Case 看板
-> 新建 Case
-> Step 1 案件基本信息
-> Step 2 上传资料包
-> Step 3 资料包预检
-> Step 4 审查范围确认
-> Step 5 自动运行预审
-> 报告页
```

交互约定：

- Step 4 点击“下一步 · 运行预审”后直接进入 Step 5 并自动开始预审，不再二次点击。
- 报告页不显示“审查范围已变更”的黄色提示条。
- Case 看板支持删除 Case。
- PDF 下载使用 `/api/cases/{case_id}/report.pdf`。
- 管理端可查看知识库、RAG chunks、规则命中、Agent 分支和 trace。

## 2. 总体后端流程

```text
创建 Case
-> 上传单文件或多文件资料包
-> 资料包预检 package_precheck
-> 文档槽位标准化：安全技术说明书 / 配方 / 工艺 / 其他资料
-> 资料解析与字段抽取
-> 资料完整性门禁 document_quality
-> 按 review_scenario + check_types 路由任务
-> RAG 检索与规则召回
-> 物料 / 工艺 / 储运 / 法规 Agent 分支判断
-> 交叉检查与主审汇总
-> customer_report 客户报告 + technical_trace 管理端证据
-> 写入 SQLite Case / Report
```

资料不足不会直接拒绝上传。系统采用软门禁：允许继续预审，但必须说明哪些结论可靠、哪些只能复核、哪些必须补件。

## 3. Case 创建与任务入口

Case 保存：

- 标题
- 审查场景 `review_scenario`
- 目标市场 `target_markets`
- 检查项 `check_types`
- 上传文档
- 最近报告
- 状态

`review_task` 仍保留给兼容和管理端调试，普通用户流程不依赖手写任务。

## 4. 资料包预检

上传后先执行 `package_precheck`。预检回答三件事：

1. 系统读懂了哪些文件。
2. 缺少哪些支撑资料或字段。
3. 本次选择的检查项哪些可直接做、哪些受限、哪些需要补件后再做。

每个文件输出：

- `filename`
- `detected_type`
- `readability`
- `confidence`
- `recognized_fields`
- `missing_fields`
- `user_message`

资料包整体输出：

- `overall_status`
- `recognized_documents`
- `missing_documents`
- `available_checks`
- `limited_checks`
- `blocked_checks`
- `supplement_actions`

未知文件不会被强行归为安全技术说明书。扫描件或不可读文件进入补件/复核路径。

## 5. 文档标准化与字段抽取

系统把可用资料映射到审查槽位：

- 安全技术说明书：章节、供应商、修订日期、登记号、分类标签、运输编号等。
- 配方：成分名称、登记号、浓度区间、保密或未知成分。
- 工艺：温度、压力、关键步骤、设备、储存条件、运输信息。
- 其他资料：供应商声明、检测报告、储运说明、未知参考资料。

字段抽取优先使用确定性解析函数。字段缺失、文本不可读、资料类型不清楚会进入 `document_quality` 和补件动作。

## 6. 资料完整性门禁

确定性门禁检查：

- 安全技术说明书 16 章节
- 供应商与修订日期
- 登记号与浓度
- 工艺温度、压力、关键步骤
- 储存条件、运输信息
- 资料包是否包含支撑所选检查项的文档类型

门禁输出进入：

- `review_workbench.document_quality`
- `review_workbench.supplement_actions`
- `customer_report.issue_groups`
- 最终 `verdict`

规则函数能稳定判断的字段、章节、硬性缺口不上 LLM。跨文件矛盾、供应商声明冲突、语义充分性不足等再进入 Agent 复核。

## 7. RAG 与规则召回

任务路由后，系统按 Agent 生成 query，并执行：

- 向量召回
- keyword 匹配
- 登记号 exact match
- jurisdiction/domain rerank
- 规则包命中

召回结果只作为证据候选。客户报告不直接展示 chunk、rerank 分数或 trace；这些内容进入管理端。

知识库未加载时，系统不会无证据放行，会输出复核或补件结论。

## 8. 子 Agent 责任边界

### 资料完整性

资料完整性以函数门禁为主，负责识别可读性、文件类型、核心字段、缺失资料和补件动作。

### 物料 Agent

物料 Agent 负责成分、登记号、浓度和组合关系。

典型问题：

- 未知登记号
- 缺浓度
- 企业红线物质
- 可燃物与氧化剂共存
- 次氯酸盐与酸类禁忌组合

### 工艺 Agent

工艺 Agent 判断工艺条件是否放大物料风险。

典型问题：

- 高温氧化剂
- 同釜混配
- 加热、加压、投料顺序不清
- 缺温度、缺压力、缺关键步骤

### 储运 Agent

储运 Agent 判断储存、隔离、运输和现场安全条件是否充分。

典型问题：

- 可燃液体缺防火通风说明
- 不相容物同储
- 运输编号与危险类别不一致

### 法规 Agent

法规 Agent 按目标市场和登记号执行初筛。

典型问题：

- 危险化学品目录命中
- 欧盟高度关注物质阈值风险
- 美国化学品清单状态复核
- 企业红线物质

## 9. 主审汇总

主审按保守优先级合成：

```text
资料不可读或关键资料缺失 -> needs_supplement
硬性红线或禁忌组合命中 -> not_approved
知识库不足、资料不足、上下文不确定 -> needs_review
无不合格、无复核、资料可支撑 -> pass
```

Case 状态映射：

- `pass` -> `ready_for_next_step`
- `needs_supplement` -> `needs_supplement`
- `needs_review` -> `needs_review`
- `not_approved` -> `not_approved`
- 未运行 -> `draft`

## 10. 客户报告结构

`customer_report` 是普通用户主视图，采用 `customer_report.v1`：

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

每条问题包含：

- `id` / `issue_id`
- `status` / `status_label`
- `severity`
- `category` / `category_label`
- `reason`
- `rule_id` / `rule_name_zh` / `rule_text`
- `user_text`
- `impact`
- `recommendation`
- `requires_human_review`

展示策略：

- 客户报告只展开不合格、复核和补件事项。
- 合规项只做汇总，不列出技术明细。
- “违反规则”使用业务准入口径。
- “执行要求”在 HTML/PDF 中标红。
- `user_text` 优先引用上传资料原文。
- 规则 ID 和常见英文标签在客户展示层映射为中文。

## 11. PDF 报告

PDF 下载接口：

```text
GET /api/cases/{case_id}/report.pdf
```

生成顺序：

1. Playwright Chromium 渲染 feature 风格打印模板。
2. Playwright 不可用时调用系统 Chrome/Edge headless。
3. 浏览器不可用时使用内置文本 PDF fallback。

HTML 报告和 PDF 使用同一份客户报告数据，红色执行要求在两端保持一致。

## 12. 管理端技术输出

以下内容只进入管理端，不进入客户报告正文：

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
