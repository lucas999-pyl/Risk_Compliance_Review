# HANDOFF #5 · 2026-05-13 晚 · Demo 数据资产重写 + user_quote bug 修 + 文案修正

> **协议方向**：OrbitOS（Brain）→ 开发端（Factory · WSL Claude Code CLI / Codex CLI）
> **OrbitOS 决策依据**：[[化工合规RAG工具#D46]]（4 子决策 D1-D4 已落项目页）
> **覆盖说明**：UI 改造（HANDOFF #4-master + 4a-4f）已落地（LOG #2 / #3a-#3f / #4，79 tests pass，9 路由 curl 200）。本轮处理 T1e 浏览器验收发现的 4 类问题。

---

## 1. 背景（用户当面拍板的 4 决策）

T1e 浏览器目测发现：
1. "用户原文"字段全填了元数据摘要（`SDS 章节数 16; 缺失字段 [无]`），不是真实文档段落 —— **后端 user_quote 输出 bug**
2. 违反规则名显示 `incompatibility_oxidizer_flammable` 等英文 ID —— **规则数据缺中文显示字段 + 报告层直接显内部 ID**
3. 状态文案 "可进入下一步" 用户读不懂"下一步是什么" —— **factory.py 状态码 + 前端文案歧义**
4. 演示文档质量差，跑预审动辄 "缺失字段 [无]" —— **演示数据资产层级烂，需重写**

用户拍板的 4 决策（详情见项目页 D46）：

| 决策 | 内容 |
|---|---|
| **D1 · 子领域** | 涂料 / 油墨（与现有 Case 名一致，沉没成本最小） |
| **D2 · Case 剧本** | 4 个 Case 覆盖 4 个 verdict：pass / needs_review / not_approved / needs_supplement，每个 = 完整 SDS+配方+工艺资料包 |
| **D3 · 修 user_quote bug** | chemical_rag.py 输出层从 chunk text 反向定位真实原文段落 |
| **D4 · 双层显示 + 中英行话混排** | 内部 `rule_id` 英文 snake_case 保留（API / trace / 管理端可见）；显示层走 `rule_name_zh` + `regulation_ref` + `regulation_excerpt`；SDS / GHS / CAS / REACH / RoHS / EHS / SVHC / GB 等行业缩写**保留英文**不硬翻 |

---

## 2. 执行架构（主 Agent 内 3 sub-Agent 并行）

```
你（主 Agent）
├── 串行根（**你自己干**）：
│     0. Read 本 HANDOFF 全文 + 项目页 D46（如已 mirror 到本仓 docs/）
│     1. 跑 `python -m pytest` 确认当前 baseline 79 tests pass（避免脏起点）
│     2. 记下当前 dev server PID（如果跑着）
│
├── 并行扇出（**单条消息内 spawn 3 个 sub-Agent**，文件域审计见 §4）：
│     ├── sub-X：演示数据资产（规则 pack JSON + 4 套 demo 资料包，**对着答案出题**）
│     ├── sub-Y：后端 user_quote bug 修（chemical_rag.py 输出层 + finding 构造）
│     └── sub-Z：前端文案 + 状态码（report/index.js + factory.py 状态码 map）
│
└── 串行收尾（**你自己干**）：
      1. 汇总 sub-Agent 各自的四段式 return → 写 ## 任务 #5a/#5b/#5c 倒序入 IMPLEMENTATION_LOG.md
      2. 清空 vector_store + import 新 demo pack
      3. 跑 4 个 Case 端到端：依次创建 → 上传对应资料包 → 跑预审 → 看报告
         **验收标准**："缺失字段 [无]" 绝迹；每条不合规的"用户原文"是文档真实段落；违反规则显中文名 + 标准号；pass 态文案不再说"可进入下一步"
      4. 写 ## 任务 #5 · Demo 数据资产重写收尾 四段式 + 4 个 case 验收路由 + 截图（如能）到 LOG 顶部
```

---

## 3. 3 个 sub-Agent 任务书

### 3.1 · sub-Agent X · 演示数据资产（规则 pack + 4 套 demo 资料包）

**工作目录锁定**：`/home/oneus/projects/化工合规工具/Risk_Compliance_Review/`

**文件域**：
- 重写 `data_samples/chemical_rag_dataset/knowledge/chemical_rules_pack.json`（**保留 schema 兼容性**：rule_id 字段名不改；新增 `rule_name_zh` / `regulation_ref` / `regulation_excerpt` / `severity` 字段）
- 重写 / 新增 `data_samples/chemical_knowledge_sources/official_pack_2026_05/*.md`（规则源文档，作为 RAG 知识库的"标准答案"）
- 新增 4 个目录 `data_samples/chemical_rag_dataset/upload_samples/case_<verdict>/` 各含一份**完整**资料包（SDS.md / formula.md / process.md），文件路径 / 命名遵循现有 manifest.json 习惯

**任务**：
1. 设计 10-15 条**演示规则**（涂料 / 油墨子领域），覆盖：
   - SDS 章节完整性核查（GB/T 16483-2008 16 章结构）
   - 危险化学品储存兼容性禁忌（GB 15603 氧化剂 / 可燃液体 / 腐蚀剂 同储禁忌）
   - 配方组分 CAS 合规性（GB 30000 系列 / REACH SVHC 清单）
   - 工艺关键参数完整性（温度 / 压力 / 关键步骤）
   - 市场准入材料完整性（出口 EU 需 REACH 注册 / 出口 US 需 TSCA / 国内需 GHS 标签）
   - GHS 标签与象形图（CLP / GB 30000.2）
   - VOC 限值（GB 30981 / 出口加州 CARB）
   - 其他你觉得专业 + 易演示的
2. 每条规则**严格按双层显示 schema**：
   ```json
   {
     "rule_id": "sds_section_completeness",
     "rule_name_zh": "SDS 章节完整性核查",
     "regulation_ref": "GB/T 16483-2008",
     "regulation_excerpt": "化学品安全技术说明书应包含 16 章内容，包括...",
     "severity": "block",
     "trigger_condition_zh": "SDS 缺失任意一章或章节内容空白",
     "expected_user_quote_keywords": ["第 X 章", "未提供", "N/A"]
   }
   ```
   `expected_user_quote_keywords` 是给 sub-Y 用的：标记 chunk text 里**应该被引用**的关键词位置
3. 4 套 demo 资料包**反向校对**（对着规则编文档）：
   - **case_pass**：完整 SDS（16 章齐全）+ 完整配方表（CAS 全标 + 含量百分比）+ 工艺说明（温度 / 压力 / 关键步骤齐）→ 预期 `pass`
   - **case_needs_review**：规则边界值，如 SDS 第 11 章毒理学资料"暂未测试"+ 配方含 SVHC 高度关注物质但含量 < 0.1%（边界）→ 预期 `needs_review`
   - **case_not_approved**：配方禁忌组合（如：氧化剂如过氧化氢 H2O2 + 可燃溶剂如乙醇 / 丙酮 同储或同配）+ 工艺无防爆措施 → 预期 `not_approved`
   - **case_needs_supplement**：上传时**缺**配方 CAS / 缺工艺关键参数 / 缺 SDS 第 7 章储运 → 预期 `needs_supplement`
4. 每份 SDS 至少有 1-2 段"足够长可被 chunk 截取"的真实正文（中英行话混排），避免 chunk 后只剩元数据
5. 更新 `data_samples/chemical_rag_dataset/manifest.json`（如有）让 4 个 case 都能被发现

**Anti-vision**：
- ❌ 不写真化工合规干货 / 不引外部标准全文 → 用 GB/REACH/GHS 编号引用 + 简短模拟原文即可
- ❌ 不引入新依赖
- ❌ 规则 pack JSON 的字段名 / schema 兼容性必须保留（不要改 rule_id 字段名）
- ❌ 不动 backend / static / 业务后端代码

**完成回报**：四段式（Done / Decisions / Blockers / Next），return 给主 Agent，不直接写 LOG 文件。在 Return 末尾附 4 个 case 目录路径 + 每个 case 预期 verdict + 主结论关键词，给主 Agent 串行收尾用。

---

### 3.2 · sub-Agent Y · chemical_rag.py user_quote bug 修 + 中文规则字段透传

**工作目录锁定**：同上

**文件域**：仅 `backend/app/chemical_rag.py`（只动 finding / customer_report 输出层，**不要碰 RAG 流水线 / chunk / vector_store / Agent 编排**）

**任务**：
1. 定位生成 `customer_report.issue_groups[].items[]` 的代码段（grep `user_quote` / `user_excerpt` / `customer_report`）
2. 改造 `user_quote` 字段填充逻辑：
   - 优先从**触发该规则的 chunk text** 截取相关原文段落（前后 50-100 字符的 snippet）
   - 用规则 pack 的 `expected_user_quote_keywords` 字段（如 sub-X 已加）做 highlight 锚点
   - 如果命中 chunk 但找不到关键词，回退到 chunk text 的前 200 字
   - **只在确实没有任何 chunk 命中时**才回退到元数据摘要（这种情况应该极少）
3. 同步透传规则的中文显示字段到 finding：
   - 在 finding 输出加 `rule_name_zh` / `regulation_ref` / `regulation_excerpt` 三个字段（从 rule pack 读）
   - 不要删除原 `violated_rule_id` 字段（前端可能还在用 / trace 仍需）
4. 确保现有 79 tests 仍 pass（如果有测试硬绑了旧 user_quote 文案，**不要为了 pass 改 demo 资料让测试通过**——告诉主 Agent 改测试断言为新逻辑）

**Anti-vision**：
- ❌ 不动 RAG 召回 / chunk / Rerank / Agent 分支逻辑
- ❌ 不动 vector_store / settings / ai_clients
- ❌ 不引新依赖

**完成回报**：四段式 return + 改动行号 + 测试结果，给主 Agent。

---

### 3.3 · sub-Agent Z · 前端报告文案 + 状态码映射

**工作目录锁定**：同上

**文件域**：
- `backend/app/static/pages/report/index.js`（或 `.html` 模板，看哪个负责"违反规则" / "可进入下一步" 文案渲染）
- `backend/app/static/pages/case-board/index.js`（看板卡片状态文案，同源问题）
- `backend/app/factory.py`（**仅** `case_status_from_customer_verdict` 函数那 7 行 + 可能的相关常量，**不要碰其他路由 / 业务逻辑**）

**任务**：
1. 修文案问题 3：状态码 `ready_for_next_step` 当前文案"可进入下一步"误导。改为：
   - factory.py 状态码 map 选项：保留 `ready_for_next_step` 不变（避免破坏既有 API），仅前端显示文案改
   - 前端报告页主结论卡（pass 态）：**移除**"可进入下一步"那行 / 改为"合规预审通过 · 已生成报告"
   - Case 看板卡片状态行（pass 态）：从"可审 · 已完成"保持或微调为"已完成 · 报告就绪"
2. 修问题 2：违反规则显示字段
   - 前端 finding 渲染时优先读 `rule_name_zh`（由 sub-Y 加上后透传过来），fallback 到 `rule_id`
   - 同时显示 `regulation_ref`（如 "GB 15603-2022 第 6.4.2 条"）作为副标题
   - `regulation_excerpt`（法规原文）显示在引用块内
   - 现有"用户原文"字段不动（sub-Y 已修内容来源）
3. 视觉对齐设计稿 07-report-default.html `.finding-tile` 段落格式（不需要改 CSS，只动 innerHTML 结构）

**Anti-vision**：
- ❌ 不动 router.js / shell.js / 其他 page 模块
- ❌ 不动 factory.py 业务路由 / 其他函数
- ❌ 不引新依赖 / 框架
- ❌ 不动报告页其他 3 态（drawer / rerun）的非文案部分

**完成回报**：四段式 return + 改动行号，给主 Agent。

---

## 4. 文件域审计（**确认 3 sub-Agent 不冲突**）

| Sub-Agent | 写入文件 / 目录 | 冲突？ |
|---|---|---|
| X | `data_samples/chemical_rag_dataset/knowledge/*` + `data_samples/chemical_rag_dataset/upload_samples/case_*/` + `data_samples/chemical_knowledge_sources/official_pack_2026_05/*` | 否（纯数据文件） |
| Y | `backend/app/chemical_rag.py`（仅 finding 输出层） | 否 |
| Z | `backend/app/static/pages/report/*` + `backend/app/static/pages/case-board/*` + `backend/app/factory.py` (case_status_from_customer_verdict 函数) | 否 |

**唯一争用点**：Y 和 Z 都改 backend/.py 文件，但是不同文件（chemical_rag.py vs factory.py），无并行写冲突。

---

## 5. 主 Agent 串行收尾（**详细步骤**）

3 sub-Agent return 后：

1. **LOG 汇总写入**（IMPLEMENTATION_LOG 是倒序，最新在顶）：
   ```
   ## 任务 #5c · 前端文案 + 状态码（sub-Z return）
   ## 任务 #5b · chemical_rag.py user_quote 修（sub-Y return）
   ## 任务 #5a · 演示数据资产 + 规则 pack 重写（sub-X return）
   ```
2. **清空 vector_store 重建**：
   ```bash
   pkill -f 'uvicorn app.main' || true
   rm -rf data/vector_store/chemical_rag
   ```
3. **重启服务**：`uvicorn app.main:app --app-dir backend --reload --port 8888` 后台跑
4. **import 新 demo pack**：调 `/chemical/knowledge/import-demo-pack` 让 sub-X 重写的 pack 入库
5. **4 case 端到端验收**：依次创建 4 个 Case（用 sub-X 提供的 4 个 case 目录上传），跑预审，**逐项核查**：
   - [ ] case_pass · 报告显示"合规预审通过 · 无不合规事项"，状态条 chip "结论·可审"
   - [ ] case_needs_review · 报告显示 N 条 needs_review，每条用户原文是 SDS / 配方 / 工艺**真实段落**（非元数据摘要），违反规则显**中文名 + GB/REACH 标准号**
   - [ ] case_not_approved · 报告显示阻断 chip，违反规则中文显示"氧化剂与可燃液体储存兼容性禁忌"类似文案
   - [ ] case_needs_supplement · 报告显示补件清单，违反规则文案带"建议补充 X 章 / X 字段"
6. **"缺失字段 [无]" 绝迹验收**：4 个 case 的报告里**完全不能再出现** `缺失字段 [无]` / `SDS 章节数 16; 缺失字段 [无]` 这类元数据兜底文案
7. **写 ## 任务 #5 · Demo 数据资产重写收尾 + 4 case 端到端验收**：
   - Done 段列 4 case 验收结果
   - Decisions 段记下任何收尾期间的妥协
   - Blockers 段如果有
   - Next 段给用户下一步建议（如截图 / 跑客户演示）

如果 4 case 中**任何一个验收不过**：在 LOG 写明哪条不过 + 推测根因，停手等用户决策。**不要自己回过头改 sub-Agent 的产物**——那样会破坏 sub-Agent 文件域纪律。

---

## 6. 全局 Anti-vision（贯穿全程）

- ❌ 不要 git commit / push / 建分支
- ❌ 不要打开 / 修改 `.env` 本体
- ❌ 不要访问 Windows `E:/AI/Mulit-agents/`
- ❌ 不要碰**业务逻辑非输出层**：RAG 召回 / Rerank / Agent 编排 / vector_store / settings / ai_clients / store / service
- ❌ 不要碰 UI 其他页面（wizard / admin-kb / admin-trace / PDF）—— 本轮仅 report + case-board 文案微调
- ❌ 不要引入 React / Vue / 框架 / 打包器
- ❌ 不要写真化工干货（这是 demo，对着答案出题就行）
- ❌ 不要让 sub-Agent 顺序 spawn（单条消息内同时派发 3 个）
- ❌ 不要让 sub-Agent 直接写 LOG / TRAPS 文件（return 内容主 Agent 串行汇总写）

---

## 7. 边界

- HANDOFF 范围内有自相矛盾 → 对应任务 LOG 写 Blocker 停手
- 4 case 端到端时如果发现 sub-X 的资料与 sub-Y/Z 的代码逻辑不匹配 → 在 LOG 写 Blocker + 推测哪边需要调整，停手等用户

---

**OrbitOS 签名**：徐钰 / OrbitOS Agent · 2026-05-13 · 决策依据 [[化工合规RAG工具#D46]]
