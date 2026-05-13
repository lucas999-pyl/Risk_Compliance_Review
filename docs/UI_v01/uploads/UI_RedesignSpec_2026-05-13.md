---
type: design-spec
project: "[[化工合规RAG工具]]"
created: 2026-05-13
status: draft
audience: Claude Design（设计稿生成）→ 徐钰 review → Factory Agent 实施
related_decisions:
  - "[[化工合规RAG工具#D37]]"
  - "[[化工合规RAG工具#D38]]"
  - "[[化工合规RAG工具#D44]]"
style_baseline: "Risk_Compliance_Review/DESIGN.md（Apple-design-analysis）"
tags:
  - UI
  - 设计文档
  - 化工合规RAG工具
---

# UI 改造设计 Spec · 2026-05-13

> 这是喂给 Claude Design 的"设计宪法"。本文规定**界面层级 / 状态 / Token / 交互边界**，不下到代码层（不选组件库、不定 API schema）。Claude Design 据此产出视觉稿，徐钰 review 后才会写 HANDOFF 下发 Factory 实施。

---

## 1 · 目标与上下文

**用户痛点**（2026-05-13 实测）：
- 跑完 5 步流程后**不知道结果在哪**——客户报告页要么被埋、要么没有
- 5 步 stepper 是装饰性的，所有内容堆在一张长页面平铺
- 右上 4 个按钮平权排布，操作者**不知道现在该按哪个**
- 中间结论（已识别 / 需补 / 可查 / 阻断）视觉权重 = 普通输入框
- 管理端是"技术细节展开器"，不是"管理员工作台"

**改造目标**：
- 操作者视角的"任务驱动"工作台，不是开发者视角的"流程展示器"
- 一眼看到结果（报告优先），过程按需展开
- 用户端 / 管理端是**同一界面 + 权限差异**，不是两个截然不同的 UI
- 客户最终拿到**一份能盖章归档的 PDF**

---

## 2 · 决策栈（向上溯源）

| 决策 | 一句话 | 影响 |
|---|---|---|
| **[[化工合规RAG工具#D37\|D37]]** | 用户端报告固定模板「编号 + 规则编号+原文 + 用户原文 + 改进建议」；检索详情迁管理端 | 报告页 §6.3 + PDF 模板 §8 的核心结构 |
| **[[化工合规RAG工具#D38\|D38]]** | 徐钰亲自做 UI（用户端 + 管理端）；彭祎来只出内核 + JSON | 本 spec 是 D38 落地物 |
| **[[化工合规RAG工具#D44\|D44]]** | 6 项拍板：A+C / 进度条双粒度 / 同 SPA / 预检自动跑 / PDF 后端渲染 / PDF 客户一档 | 本 spec 的 6 个执行边界 |

---

## 3 · 风格基底：Apple 美学语汇 + B 端工具适配

完整 token 见 WSL 仓 `Risk_Compliance_Review/DESIGN.md`。**本节只列对本项目最关键的 10 条 + B 端适配**。

### 3.1 · 直接沿用

- **单色调 Action Blue** `#0066cc`：所有"点我"信号（CTA、链接、focus ring、当前步骤指示）。**禁止引入第二个品牌色**
- **字体梯**：SF Pro Display（600 weight，display-lg 40px / hero 56px）+ SF Pro Text（400 weight，body 17px）；**weight 500 不存在**
- **负字距**：display 尺寸 -0.28 ~ -0.374px，得到"Apple tight"标题节奏
- **边到边交替明暗 tile**：白底 `#ffffff` ↔ 米白 `#f5f5f7` ↔ 近黑 `#272729`——**颜色变化本身就是分隔**，禁止再加 border / shadow
- **极致留白**：tile 顶 64-80px 气，按钮 padding 11×22px，盲打不挤
- **Pill 形 CTA** `border-radius: 9999px`：主行动专用；工具按钮用 8px sm 矩形
- **零装饰阴影**：唯一的 `rgba(0,0,0,0.22) 3px 5px 30px` 留给**报告页"主结论"卡片**（充当"产品照片"的角色，是这个工具的"主角"）
- **scale(0.95) 按下态**：所有按钮统一微交互

### 3.2 · 中文化适配（本项目自定）

| Apple 原 token | 中文替代 | 原因 |
|---|---|---|
| `SF Pro Display, system-ui, -apple-system, sans-serif` | `"PingFang SC", "SF Pro Display", system-ui, -apple-system, sans-serif` | 苹方 SC 是 SF Pro 的中文配套设计，weight 600 形态最接近 |
| `SF Pro Text` 17px body | 苹方 SC 16px body（line-height 1.6 而非 1.47） | 汉字默认 16px 是中文 Web 共识；汉字密度大需要更松行距 |
| display 56px hero | display 48px hero | 汉字高密度，56px 视觉过重 |
| 字重 600 | 字重 600 不变（苹方 SC Semibold） | 一致 |

### 3.3 · 新增语义色（克制使用）

| Token | Hex | 用途 |
|---|---|---|
| `status-pass` | `#34c759` | "可审 / 合规 / 已识别"——只用作 chip 小色点 / 进度条已完成段 |
| `status-warn` | `#ff9500` | "需复核 / needs_review"——只用作 chip |
| `status-block` | `#ff3b30` | "阻断 / not_approved / 缺件"——只用作 chip 与少量小字 |
| `status-mute` | `#8e8e93` | "未运行 / 待办"——chip / 灰态 |

**禁止**：把这 4 个色当背景填充用、当 CTA 用、当大面积装饰用。**Action Blue 仍然是唯一的"点我"色**；状态色只表态，不引导操作。

### 3.4 · 禁忌（来自用户铁律 + 本项目）

- **禁用 emoji 类别图标**（与 Apple 美学冲突）—— 状态用色点 + 中文文字
- **禁用罗马数字**（统一阿拉伯）—— Step 1 / 2 / 3，不是 I / II / III
- **不引入装饰性渐变**——氛围靠"边到边交替 tile"达成
- **不给卡片 / 按钮 / 文字加 shadow**——shadow 只给报告页"主结论"卡
- **不混用圆角语法**——sm 8px（工具）/ lg 18px（卡片）/ pill 9999px（CTA），中间值不出现

---

## 4 · 信息架构（同 SPA + 权限切换）

```
全局壳
├── 顶部 global-nav（44px 高，黑底 #000，右上角"客户预审 ↔ 管理端"切换器）
├── 左侧 Case 列表（240px 宽，固定常驻，#fafafc pearl 底）
└── 主工作区（弹性宽，可达 1440px 内容锁）
    ├── 顶部进度条（详见 §7）
    └── 主体内容（按当前路由切换）
        ├── /cases · Case 看板（空 Case 时的首页）
        ├── /cases/:id/new · 新 Case Wizard（5 步）
        ├── /cases/:id · 已有 Case 报告页（默认视图）
        ├── /admin/kb · 管理端·知识库工作台（仅管理员可见）
        └── /admin/cases/:id/trace · 管理端·审查回放（仅管理员可见）
```

**权限差异**（同一 SPA 内）：
- 用户端：只看到 `/cases/*` 路由 + 报告页右侧抽屉**没有"证据 / Agent / 规则"3 个 tab**
- 管理员：多 `/admin/*` 路由 + 报告页右侧抽屉**多出 3 个 tab**（RAG 证据 / Agent 分支 / 规则匹配）

切换器（顶部右上角）：仅管理员可见。点击在"客户预审视角"（看到的就是用户看到的）和"管理端视角"（解锁所有抽屉 + admin 路由）间切换。**这是权限演示器，不是两个独立产品**。

---

## 5 · 主旅程（happy path · 单 Case 状态流）

```
[创建空白 Case]
    └→ Wizard Step 1（案件基本信息）
        └→ Wizard Step 2（上传资料包 → 自动预检）
            └→ Wizard Step 3（预检结论卡 → 可直接进 Step 4）
                └→ Wizard Step 4（勾选审查项 / 调整范围）
                    └→ Wizard Step 5（运行预审 → 实时子任务进度）
                        └→ 报告页（Report-first，永久默认视图）
                            ├→ 状态条（紧凑横排 metric）
                            ├→ 不合规四件套清单（D37 口径）
                            ├→ 顶部"下载 PDF"按钮
                            └→ 右侧时间线抽屉（回看任意上一步 / 管理员看证据）
```

**关键规则**：
- 进行中的 Case（未完成 Step 5）再次打开 → 自动跳回**该走的下一步**那屏
- 已完成的 Case 再次打开 → **永远默认落在报告页**，不是回到 Step 5
- 任何时候点击左侧 Case 列表项 → 立即切换到该 Case，主工作区按上述规则决定显示哪屏

---

## 6 · 页面 wireframe

### 6.1 · Case 看板（首页 · 空 Case 时落地）

**目标**：1 屏看全工作队列，识别下一个要处理的 Case。

**层级**：
- 顶部：**`新建 Case`** 主 CTA（Pill 形 Action Blue，右上角；左上角空着，让"创建"成为视觉焦点）
- 主体：**Case 卡片网格**（3 列 desktop / 2 列 tablet / 1 列 phone）
  - 每张卡片 = store-utility-card 风格（白底 + hairline `#e0e0e0` + 18px 圆角 + 24px padding）
  - 卡片内层级：
    - 顶部小字（caption 14px / 400）：Case 编号 + 创建日期
    - 标题（body-strong 17px / 600）：案件标题
    - 中段（caption 14px / 400）：审查场景 · 目标市场
    - **关键产出条**（chip 横排）：「3 份资料」「0 需补」「6 可查」「1 阻断」「报告就绪 / 待运行 / 第 N 步进行中」
    - 右下 text-link：「查看报告 →」 或 「继续 →」（按 Case 状态二选一）
- 空态：居中放一句 `display-md` "还没有 Case，从右上角"新建 Case"开始"

**不要**：
- 不要做"筛选 / 排序"工具栏（V1 不要，等 Case 数 >20 再加）
- 不要在卡片内塞操作菜单（"删除 / 重命名"放进卡片详情，不要外露）

### 6.2 · 新 Case Wizard（5 屏 · 严格一步一屏）

**Step 1 · 案件基本信息**
- 屏内只 3 个 input：案件标题 / 审查场景（下拉：市场准入 / 配方合规 / SDS 复核 …）/ 目标市场（CN / EU / US 多选 chip）
- 底部：左「上一步」（灰态）+ 右「下一步」（Pill 形 Action Blue，激活态需要至少填完标题）
- 顶部进度条：1/5

**Step 2 · 上传资料包（自动预检）**
- 屏内主体：大号 dropzone（虚线 hairline 边 + 18px 圆角 + 居中文案"拖拽文件到此 · 或点击选择"）
- 上传中 → dropzone 变进度态（条形 progress + 当前文件名 + N/M 文件计数）
- 上传完成 → **自动跑预检**（dropzone 折叠为"3 个文件已上传"摘要 + 下方出现 Step 3 预检结论卡）
- **无显式"运行预检"按钮**（D44 拍板 ④）

**Step 3 · 预检结论卡**
- 4 张 metric 卡横排（store-utility-card 风格 + 24px padding + hairline 边）：
  - 「已识别 · 3」（status-pass 色点）
  - 「需补件 · 0」（status-mute 色点 / 有数字时变 status-warn）
  - 「可直接检查 · 6」（caption 灰字"6 个检查项可走"）
  - 「受限阻断 · 1」（status-block 色点 / 有数字时高亮）
- 卡片下方：每个文件一行（文件名 + 类型 chip + 识别置信度 + 一句话说明）
- 阻断态：屏底自动弹"需补件清单"卡（status-block 色点 + 缺失项列表 + "上传补件"按钮回 Step 2）

**Step 4 · 审查范围**
- 屏内主体：检查项清单（按"物料 / 工艺 / 储运 / 法规适配"4 大类分组）
- 每项一行：复选框 + 检查项名称 + caption 灰字"对应规则编号 + 一句话说明"
- 系统默认勾选场景推荐项（按 Step 1 的"审查场景 + 目标市场"算出）
- 用户可调整勾选范围；右上 text-link「全选 / 全不选 / 恢复推荐」

**Step 5 · 运行预审**
- 屏内主体：一个大型「运行预审」Pill 按钮（首次点击）
- 点击后按钮消失，原位变成**子任务进度卡**（详见 §7.1）
- 子任务跑完 → 自动跳到报告页（§6.3），无需用户再点

### 6.3 · 客户报告页（Report-first · 永久默认视图）

**这是改造的核心**——已有 Case 的"家"。

**层级（从上到下）**：

1. **紧凑状态条**（顶部贴在进度条下方，64px 高 + 32px padding + canvas-parchment 底）：
   - 左：Case 编号 + 案件标题（body-strong）
   - 中：横排 chip 摘要「已识别 3 · 需补 0 · 可查 6 · 阻断 1 · **结论：需复核**」（结论 chip 用 status-warn）
   - 右：**`下载 PDF`** Pill 按钮（Action Blue）+ 「打开抽屉」icon 按钮（44px 圆形）

2. **主结论卡**（页面正中 · 唯一带 shadow 的元素 · 占满内容宽 · 80px 内边距）：
   - 顶部色点 + 大字（display-md 34px / 600）："需复核"
   - 副本（lead 28px / 300 airy）：一句话总结审查员要关注什么
   - 底部小字（caption 14px / 400）：审查日期 · 规则库版本（隐藏在客户视图，管理员可见）
   - **这张卡是 Apple 风格里"产品照片"的位置**，是页面唯一的视觉锚点

3. **不合规四件套清单**（主结论卡下方，每条一张 light tile 边到边铺，相邻两条用 parchment ↔ white 颜色交替分隔）：
   - 每条结构（严格按 D37 口径）：
     ```
     [01]                                      [严重度 chip · status-block]
     违反规则  ⌜ GB-XXX 第 X.X 条 ⌝
              ⌞ "规则原文一两句话"          ⌟
     
     用户原文  ⌜ 用户上传资料里相关的那段原文     ⌟
     
     改进建议  一句到三句话的具体改进意见
     
                                            [查看证据 →]（仅管理员可见）
     ```
   - 编号用 caption-strong 14px / 600
   - "违反规则 / 用户原文 / 改进建议"标签用 caption / mute 灰 14px / 400
   - 内容用 body 17px / 400
   - "查看证据"链接（管理员可见）→ 打开右侧抽屉到该条的 RAG 证据 tab

4. **底部签发位**（仅在打印 PDF 时可见 · Web 视图隐藏）

5. **右侧时间线抽屉**（默认收起，点状态条右侧 icon 展开）：
   - 抽屉宽 400px，从右侧滑入
   - 顶部："审查流程时间线"
   - 时间线节点（5 个，对应 Wizard 5 步）：每个节点可点 → 跳回该步骤的只读视图
   - 管理员视图额外多 3 个 tab（"RAG 证据 / Agent 分支 / 规则匹配"）切换抽屉内容

### 6.4 · 管理端·知识库工作台（`/admin/kb`）

**目标**：管理规则源 / 切块 / 向量化，与具体 Case 无关。

**层级**：
- 顶部：4 张 metric 卡（知识源数 / Chunk 数 / 向量数 / Embedding 模型）—— store-utility-card 风格
- 主体上：「上传官方知识源文档」+ 「查看已上传 Chunk」+ 「清空知识库」3 个 Pill 按钮（清空按钮用 ink #1d1d1f 黑底警示态，不是红色 —— Apple 不用红色按钮）
- 主体中：知识源 Manifest 上传区（dropzone）+ 5 份源文档上传区
- 主体下：已索引规则列表（每条一行：规则编号 + 名称 + 类型 chip + chunks 数 + 检索时间戳）

**不要**：
- 不要再在这页放"流程节点 / RAG 链路 / Agent 分支 / TopK / Rerank / 流程回放"—— 那些迁去 §6.5

### 6.5 · 管理端·审查回放（`/admin/cases/:id/trace`）

**目标**：某次具体 Case 的全链路证据视图。从报告页"查看证据"或左侧 Case 列表"管理员视角"进入。

**层级**：
- 顶部：Case 元信息条（同 §6.3 状态条）
- 主体：左右两栏
  - 左栏 320px：10 节点流程图（垂直时间线，节点点亮 + 当前节点转圈）——见 §7.2
  - 右栏弹性：选中节点的输入 / 输出 / 命中规则 / TopK / Rerank 分数（折叠面板，默认全部折叠，点击展开）

**关键**：这页是给徐钰 / 彭祎来排错用的，不会出现在用户视图。客户 PDF 也不带这些。

---

## 7 · 进度条规格

### 7.1 · 用户端中粒度（顶部常驻）

**总步骤条**（贴在 global-nav 下方，2px 高，全宽）：
- 已完成段：Action Blue `#0066cc` 实色
- 当前段：Action Blue 50% 透明
- 未完成段：hairline `#e0e0e0`
- 5 段等宽 / 4 个分段点

**当前步骤名条**（进度条正下方，44px 高 + canvas-parchment 底）：
- 左：当前步骤名（caption-strong 14px / 600，例如"Step 3 · 资料包预检"）
- 中：当前子任务文案（caption 14px / 400 mute 灰，例如"识别 SDS · 识别配方 · 校验完整性"——已完成的子任务划黑线）
- 右：占位

**Step 5 运行预审时的子任务卡**（Wizard 内大块进度卡）：
- 4-6 个子任务（识别物料 · 检索规则 · 多 Agent 分析 · 主审合并 · 交叉质检 · 生成报告）
- 每个子任务一行：色点 + 任务名 + 状态文案
- 状态：未开始（mute）/ 进行中（status-warn + 转圈）/ 完成（status-pass + 划黑线）
- 失败：单条变 status-block + "重试" text-link

### 7.2 · 管理端细粒度回放（§6.5 左栏）

- 10 节点垂直时间线（加载任务 · 解析 SDS · 解析配方 · 解析工艺 · RAG 召回 · Rerank · Agent 分支 · 主审 · 交叉质检 · 生成报告）
- 每节点：色点（status-pass / status-warn / status-block / status-mute）+ 节点名 + 耗时（caption）
- 点击节点 → 右栏切换为该节点的详情
- 全部用 Action Blue / status 色点表达，**禁止用 emoji 图标**

---

## 8 · PDF 客户报告模板

### 8.1 · 实现路径（D44 ⑤）

- 后端路由：`GET /api/cases/{id}/report.pdf`
- 实现：FastAPI 后端起 headless chromium（Puppeteer/Playwright），渲染专用打印模板 `/print/cases/:id/report`（一个无 nav / 无抽屉 / 印刷态样式的内部 SPA 路由）→ chromium 导出 PDF
- **与 Web 报告页共用同一份数据 + 同一组件库**，只是套印刷态 CSS

### 8.2 · 版式

- 页面：A4 纵向（210 × 297mm），上下边距 25mm，左右 20mm
- 字号：body 11pt / heading 14pt / hero 24pt（汉字密度高，比 Web 缩比例）
- 字体：苹方 SC（PDF 嵌入子集）/ 无衬线
- 单色 Action Blue 印刷下也保留（chip / 链接色），但**灰度打印必须可读**——验收时强制走一遍黑白打印
- 不用 backdrop-filter / shadow（chromium PDF 渲染这些会糊）

### 8.3 · 内容结构（D44 ⑥）

```
┌─────────────────────────────────────────┐
│ [审查报告 · 一段抬头小字]               │  ← 12pt mute
│                                         │
│ 案件标题                                │  ← 24pt 600
│ Case 编号 · 审查场景 · 目标市场          │  ← 14pt 400
│ 审查日期 2026-XX-XX                     │
│                                         │
│ ─────────────────────                  │  ← hairline
│                                         │
│ 审查结论                                │  ← 14pt 600
│ ┌───────────────────────────┐          │
│ │ 需复核 / 可审 / 不可审 / 待补  │  ← 18pt 600 + status 色块
│ │ 一句话总结审查员要关注什么     │  ← 11pt 300
│ └───────────────────────────┘          │
│                                         │
│ 资料清单                                │  ← 14pt 600
│ - file1.pdf · SDS 安全技术说明书 · 高置信 │
│ - file2.xlsx · 配方/成分表 · 高置信     │
│ - file3.docx · 工艺说明 · 高置信         │
│                                         │
│ ─────────────────────                  │
│                                         │
│ 不合规事项（按 D37 四件套）             │  ← 14pt 600
│                                         │
│ [01]  违反规则 GB-XXX 第 X.X 条          │  ← 编号 11pt 600
│       "规则原文……"                      │  ← 11pt 400
│       用户原文："……"                    │
│       改进建议：……                      │
│                                         │
│ [02]  ……                               │
│                                         │
│ ─────────────────────                  │
│                                         │
│ 审查员 _________   签字日期 _______      │  ← 11pt 400 + 下划线
│ 复核员 _________   签字日期 _______      │
│                                         │
│ ─────────────────────                  │
│ 页脚: Case 编号 · 生成时间 · 第 N 页     │  ← 9pt mute
└─────────────────────────────────────────┘
```

### 8.4 · 触发入口

- 报告页（§6.3）顶部状态条右侧「下载 PDF」按钮（Pill 形 Action Blue）
- 点击 → 后端生成 → 浏览器直接下载 `<Case编号>_审查报告_<YYYYMMDD>.pdf`
- 生成耗时预期 ≤ 3s；超过则 toast"正在生成报告"+ 进度

### 8.5 · 不进 PDF（D37 + D44 ⑥ Anti-vision）

- ❌ RAG 命中切块 / TopK / Rerank 分数
- ❌ 多 Agent 分支 trace
- ❌ 内部规则库版本号 / Manifest 指纹
- ❌ 任何 v1.X 版本号 / changelog / 方案 A/B 标签
- ❌ "本系统由 XX 提供"等内部品牌字样（除非客户合同要求）

---

## 9 · 状态机与边界态

| 场景 | 显示 |
|---|---|
| 全新用户登录 / 0 Case | Case 看板空态（§6.1 末尾） |
| 进行中 Case（Step 1-5 未完成） | 自动跳到该 Case 的 Wizard 下一步 |
| 已完成 Case | 默认报告页（§6.3） |
| 已完成 + 用户改了 Step 4 范围 | 报告页变"待重跑"态——状态条 chip 显「数据已变更，请重跑预审」+ 主结论卡变 mute 灰 + 出现"重新运行"Pill |
| 资料包预检阻断（缺件） | Wizard Step 3 自动弹补件卡，"下一步"按钮 disable |
| Step 5 运行失败 | 子任务卡里失败那一行变 status-block，整体允许"重试" / "查看详情（管理员）" |
| PDF 生成失败 | 按钮回弹 + toast 错误码 + 重试按钮 |
| 无权限访问 admin 路由 | 路由级 403，跳回 `/cases` |

---

## 10 · 设计 token 适配表（中文化 + 新增）

完整 token 表见 `Risk_Compliance_Review/DESIGN.md`。本表只列**本项目对原表的增量**：

| Token 类 | 原值 | 本项目值 | 备注 |
|---|---|---|---|
| `font.display` | SF Pro Display | `"PingFang SC", "SF Pro Display", system-ui` | 中文优先 |
| `font.text` | SF Pro Text | `"PingFang SC", "SF Pro Text", system-ui` | 中文优先 |
| `font.body.size` | 17px | 16px | 中文 Web 共识 |
| `font.body.line-height` | 1.47 | 1.6 | 汉字密度需要更松行距 |
| `font.hero-display.size` | 56px | 48px | 汉字高密度 |
| `color.status-pass` | — | `#34c759` | 新增 · 合规 / 已识别 |
| `color.status-warn` | — | `#ff9500` | 新增 · 复核 / 警示 |
| `color.status-block` | — | `#ff3b30` | 新增 · 阻断 / 缺件 |
| `color.status-mute` | — | `#8e8e93` | 新增 · 未运行 / 待办 |
| `component.metric-card` | — | 复用 store-utility-card 形态 | 新组件名，结构同 |
| `component.progress-bar-top` | — | 2px 高 / Action Blue 实色 + 50% 透明 + hairline 三态 | §7.1 |
| `component.case-list-item` | — | 复用 store-utility-card + caption + chip 横排 | §6.1 |
| `component.finding-tile` | — | 边到边 light/parchment 交替 tile + 80px 内边距 | §6.3 不合规四件套 |
| `component.print-template` | — | A4 / 苹方 SC 嵌入 / 无 nav / 无抽屉 | §8 |

---

## 11 · Anti-vision（本 spec 不做的事）

- ❌ **不选组件库**——React/Vue/原生由 Factory 当前栈决定，本 spec 描述视觉与状态而非框架
- ❌ **不定 RAG 接口 JSON schema**——D38 边界，彭祎来负责
- ❌ **不做"筛选 / 排序 / 标签"类工作流工具栏**——Case 数 >20 再考虑
- ❌ **不做用户管理 / 权限矩阵 UI**——V1 只做"客户预审 ↔ 管理端"二档切换器
- ❌ **不做多语言**——首发只中文
- ❌ **不做暗色模式**——Apple 风格本身就是日间主导，灯具效果靠交替 tile，不需要 dark variant
- ❌ **不做移动端响应式精细优化**——B 端工具桌面优先，phone 只保证不崩，不投资体验
- ❌ **不在客户 PDF 上加任何内部演进痕迹**（v1.X / changelog / 方案 A/B / Agent / RAG 等术语一律不入）

---

## 12 · 交付给 Claude Design 的产出清单

Claude Design 收到本 spec 后，应按这个清单生成视觉稿（HTML/CSS or Figma frames）：

1. **Case 看板**（§6.1）—— 1 张：3 列 desktop 主态 + 空态
2. **新 Case Wizard**（§6.2）—— 5 张：Step 1-5 各一张
3. **客户报告页**（§6.3）—— 3 张：默认态 / 抽屉打开态 / "待重跑"态
4. **管理端·知识库工作台**（§6.4）—— 1 张
5. **管理端·审查回放**（§6.5）—— 1 张：含 10 节点时间线
6. **PDF 打印模板**（§8）—— 2 张：第 1 页（抬头 + 结论 + 资料清单 + 第一条不合规） + 第 N 页（连续不合规清单 + 签发位）
7. **进度条组件**（§7.1 + §7.2）—— 1 张：3 种态对照（全局顶条 / 子任务卡 / 管理端 10 节点）
8. **设计 token 摘要图**（§3 + §10）—— 1 张：色板 + 字体梯 + 圆角 + 间距

**总计 13 张视觉稿**。每张需标注：使用的 token、关键尺寸、状态变体（默认 / hover / active / disabled / loading / error）。

---

## 附录 A · 与现有界面的对照（用户 2026-05-13 截图）

| 现状（截图） | 改造后（本 spec） |
|---|---|
| 5 步 stepper 装饰性，全部内容堆一页平铺 | Wizard 严格一步一屏，stepper 升级为顶部 2px 进度条 |
| 右上 4 个按钮平权排布 | 每屏只有一个主 CTA（Pill 形 Action Blue），二级动作降级为 text-link |
| 预检 4 张统计块视觉权重 ≈ 输入框 | 4 张升级为 store-utility-card 风格，是 Step 3 屏的唯一主角 |
| 客户报告页不知道在哪 | Report-first：已有 Case 默认就是报告页，主结论卡是页面视觉锚点 |
| 管理端是技术细节展开器（10 节点 + 6 折叠面板） | 拆为两个独立页：知识库工作台（§6.4）+ 审查回放（§6.5） |
| Case 列表卡内容空 | 卡内加 chip 横排关键产出 + text-link "查看报告 →" |
| 无 PDF 导出 | 报告页顶部"下载 PDF"按钮 + 后端 Puppeteer 渲染 |

---

> **本 spec 状态**：draft → 等 Claude Design 出视觉稿 → 徐钰 review → 写 HANDOFF #3 下发 Factory 实施。
> **更新此 spec 的纪律**：若设计稿评审中出现与本 spec 冲突的拍板，回来更新本文件 + 在项目页加新 D 决策块，不要让设计稿和 spec 不同步。
