# HANDOFF #4b · 2026-05-13 · UI Phase 2b · Wizard 5 步（新建 Case 全流程）

> **协议方向**：OrbitOS → 开发端（Factory · WSL）
> **依赖**：HANDOFF #3（Phase 1 串行根）已完成；本轮严格遵守其 §4.3 router 契约、§4.4 shell.js 暴露的 `setProgress / setStepbar`、§4.5 `api.cases.*` / `api.knowledge.*` 客户端封装
> **决策依据**：[[化工合规RAG工具#D37]] / [[化工合规RAG工具#D44]] · 设计稿 `docs/UI_v01/02-wizard-step1.html` ~ `06-wizard-step5.html`（只取 `.frame` 内部） · spec §6.2 / §7.1

---

## 1. 目标路由（两条 mount 同一入口）

| Hash | 含义 |
|---|---|
| `#/cases/new?step=N` | 进入"新建 Case"流；N 缺省=1。Step 1 提交后立即跳到下条 |
| `#/cases/:id/new?step=N` | 已有未完成 Case 继续 Wizard；从 URL 读 step 渲染对应屏；N=1..5 |

mount 函数从 `params.step` 读步骤，从 `params.id` 决定是否带 caseId；两条路由共用同一个入口模块。

---

## 2. 文件清单（新建 5 文件）

```
backend/app/static/pages/wizard/
├── index.js          ← registerRoute("#/cases/new") + registerRoute("#/cases/:id/new")；按 step 派发到 renderStepN
├── wizard.css        ← .wzbody / .wzfoot / .field / .toggle-chips / .dropzone / .uplist / .mc-grid / .file-ident / .scope-group / .scope-row / .runcard / .alert-card / .spinner（全部从 02-06 html 抽取 `.frame` 内 page-specific 段，不再造 nav/sidebar/pbar/stepbar）
├── steps.js          ← 5 个 renderStepN(outlet, ctx) 函数；共享 ctx = { caseId, draft, precheck, scope, runStatus }
├── precheck.js       ← Step 2 上传后自动 precheck 的轮询/状态机
└── runner.js         ← Step 5 子任务卡进度驱动（轮询 api.cases.runReview 状态）
```

---

## 3. 5 屏（严格一步一屏，禁止合并）

**Step 1 · 案件基本信息**（设计稿 `02-wizard-step1.html`）
- 3 个 input：案件标题（text）、审查场景（select，固定 4 个选项见设计稿）、目标市场（toggle-chips 多选 CN/EU/US/KR/JP）
- 主 CTA「下一步」：标题非空 + 至少选 1 个市场才激活 → `api.cases.create({title, scenario, markets})` → 拿 `id` → `navigate('#/cases/'+id+'/new?step=2')`
- 顶部进度：`shell.setProgress(1, 5, '填写标题')`

**Step 2 · 上传资料包**（设计稿 `03-wizard-step2.html`）
- 大号 dropzone（drag+drop / 点击选文件）+ 上传列表（每行 PDF/XLS/DOC 图标 + 名称 + 大小 + 进度条 + 状态 chip）
- 上传：`api.cases.uploadDocuments(caseId, files)`；完成后**自动触发 precheck**，**无显式"运行预检"按钮**（D44 拍板 ④）
- precheck 状态通过轮询/状态字段判断，全部成功后自动 `navigate('#/cases/'+id+'/new?step=3')`
- 顶部进度：`shell.setProgress(2, 5, '上传文件 / 自动预检')`

**Step 3 · 预检结论卡**（设计稿 `04-wizard-step3.html`）
- 4 张 metric 卡（已识别 / 需补件 / 可直接检查 / 受限阻断），数据来自 precheck 返回
- 文件识别明细行（类型 chip + 置信度 + 一句话说明）
- **阻断态**：底部出现 `alert-card` 列出受限项 + 「上传补件」回 Step 2 按钮；主 CTA 文案改"已知悉，继续"（仍允许前进，会在报告标记）
- 「下一步」→ `navigate('#/cases/'+id+'/new?step=4')`

**Step 4 · 审查范围**（设计稿 `05-wizard-step4.html`）
- 4 大类分组：物料 / 工艺 / 储运 / 法规适配，共 18 项；后端给出场景推荐勾选集
- 每行 scope-row（复选 + 名称 + 副标 + 规则编号）；用户可改；右上「全不选 / 恢复推荐」link
- 顶部 stepbar 实时显示「已选 N / 共 18」
- 「下一步」→ `navigate('#/cases/'+id+'/new?step=5')`

**Step 5 · 运行预审**（设计稿 `06-wizard-step5.html`）
- 首屏一个大型「运行预审」Pill 主 CTA
- 点击前先检查 `api.knowledge.status()`：若 `chunk_count === 0` → 静默自动 `api.knowledge.importDemoPack()` 兜底（修旧 UI 闸门 bug，参见 IMPLEMENTATION_LOG #1 现场补充；**不要暴露为按钮**）
- 然后 `api.cases.runReview(id, {scope})` → 按钮原位变 `runcard`：整体进度条 + 6 子任务行（识别物料 / 检索规则 + Rerank / 多 Agent 分支 / 主审合并 / 交叉质检 / 生成报告），状态：未开始(mute) / 进行中(spinner+warn) / 完成(pass+划线) / 失败(block+重试 link)
- 整体完成 → 自动 `navigate('#/cases/'+id)`（报告页由 4c Agent 实现）

---

## 4. 与 Phase 1 契约衔接

- 顶部进度条 + stepbar：每屏调一次 `window.shell.setProgress(step, 5, currentTaskName)` + `window.shell.setStepbar(stepName, tasksHTML)`，**不要自己重写 `.pbar / .stepbar` 结构**
- 路由注册：`registerRoute("#/cases/new", mount)` + `registerRoute("#/cases/:id/new", mount)`；mount 是 async 函数；切路由时 outlet 自动清空，无需自卸载逻辑
- API：只用 §4.5 `api.cases.{create,get,uploadDocuments,runReview}` 与 `api.knowledge.{status,importDemoPack}`；不要新增 endpoint
- 样式：tokens.css / shell.css 已加载；本页只引 wizard.css，不重复声明 `--primary` 等 token

---

## 5. Anti-vision（严格遵守）

1. 不动 `static/pages/wizard/` 之外任何文件
2. 不动任何 `.py`
3. 不重写 nav / sidebar / pbar / stepbar（用 shell 暴露 API）
4. 报告页不在本轮范围（4c 负责），Step 5 完成只 `navigate('#/cases/'+id)`
5. 不引入框架 / 打包器 / 第三方依赖；纯 ES Modules + 原生 DOM
6. **不要**把"运行预检""导入知识库"做成显式按钮——一律后台自动
7. 不打 `.caption` 段标注帧；那是设计稿包装，不进生产代码

---

## 6. 验收 smoke

- [ ] `python -m pytest` 仍 79 pass（本轮纯前端，不应回归）
- [ ] `uvicorn` 起服务无 error；`curl -sI /static/pages/wizard/index.js` 200
- [ ] 浏览器：`#/cases/new?step=1` 渲染 Step 1；填表 → 跳 Step 2 带新 caseId
- [ ] Step 2 dropzone 拖入文件正常上传，列表逐行进度，全部完成后**自动**跳 Step 3
- [ ] Step 3 metric 卡数字与后端 precheck 一致；阻断态出现 alert-card；点「下一步」跳 Step 4
- [ ] Step 4 推荐项预勾选；调整勾选 stepbar 计数实时变；跳 Step 5
- [ ] Step 5 点主 CTA → 6 行 runcard 顺序点亮 → 完成后 hash 自动变 `#/cases/:id`
- [ ] 5 屏视觉与设计稿 02-06 `.frame` 内部一致（间距 / 圆角 / 字号 / 色板）
- [ ] DevTools Console 无 error / warning

---

## 7. 回传

### 7.1 · `IMPLEMENTATION_LOG.md` 顶部追加

```markdown
## 任务 #3b · 2026-05-13 HH:MM · UI Phase 2b Wizard 5 步

**完成 / Done**：5 屏 mount + precheck 自动化 + Step 5 子任务卡 + 演示知识包兜底
**决策 / Decisions**：步骤切换用 hash 而非内存态，刷新可恢复；……
**阻塞 / Blockers**：无 / 具体描述
**下一步 / Next**：等 4c 报告页接入后做端到端联调
```

### 7.2 · 踩坑写 `NEW_TRAPS.md`（特别关注：上传 multipart/FormData 与 fetch 默认行为、轮询频率与 stale closure、Pill 按钮原位替换为卡片的 DOM 复用陷阱）

---

## 8. 边界

- 不 git commit / push / 建分支
- 不动 `.env` / 业务后端 / 测试套件
- 不访问 Windows `E:/AI/Mulit-agents/`
- HANDOFF 范围内自相矛盾 → 写 Blocker 停手

---

**OrbitOS 签名**：徐钰 / OrbitOS Agent · 2026-05-13 · 决策依据 [[化工合规RAG工具#D44]] / [[化工合规RAG工具#D45]]
