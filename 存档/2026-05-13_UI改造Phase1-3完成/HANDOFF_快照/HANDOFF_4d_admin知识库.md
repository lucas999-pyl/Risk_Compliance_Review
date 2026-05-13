# HANDOFF #4d · 2026-05-13 · UI Phase 2d · 管理端·知识库工作台（`#/admin/kb`）

> **协议方向**：OrbitOS（Brain）→ 开发端（Factory · WSL Codex CLI / Claude Code CLI）
> **前置依赖**：HANDOFF #3 Phase 1 已完成（壳 + tokens + router + StaticFiles）。本轮严格遵守 #3 §4.3 router.js 契约与 §4.5 api.js 契约，**不复述**。
> **决策依据**：[[化工合规RAG工具#D45]] · 设计稿 `docs/UI_v01/10-admin-kb.html` · 设计 spec `UI_RedesignSpec_2026-05-13.md` §6.4

---

## 1. 目标路由 · 鉴权

- 路由：`#/admin/kb`（管理端独占）
- 鉴权：mount 时读 `localStorage.role`，非 `"admin"` 立即 `navigate("#/cases")` 并 return（V1 演示用，纯前端守卫，不动后端）

---

## 2. 文件清单（新建 3 个）

```
backend/app/static/pages/admin-kb/
├── index.js         ← 入口，registerRoute("#/admin/kb", mount)
├── admin-kb.html    ← 模板片段（main 区内部，不含 frame / nav / sidebar）
└── admin-kb.css     ← page-specific 样式（kb-mc-grid / kb-uploads / kb-rules / cta-dark / adm-hd / adm-body）
```

`index.js` 内 `mount(outlet, params)`：fetch `admin-kb.html` → 注入 outlet → 动态加载 css → 拉数据填渲染 → 绑事件。

---

## 3. 设计稿移植（蓝本 `docs/UI_v01/10-admin-kb.html` 的 `.frame > .main`）

**必须包含**（按视觉层级）：

1. **`.adm-hd`**：标题"知识库工作台" + lead 文案 + 右侧 3 个 Pill 按钮：
   - `cta-primary`「上传官方知识源文档」（蓝底，打开 Manifest + 源文档双 dropzone modal）
   - `cta-pearl`「查看已上传 Chunk」（淡灰底，打开 Chunk 列表抽屉/modal，或预留 stub）
   - `cta-dark`「清空知识库」（**ink 黑底警示态，不是红色** —— Apple 不用红色按钮）
2. **`.kb-mc-grid`** 顶部 4 张 metric 卡（store-utility-card 风格）：
   - 知识源数 / Chunk 数 / 向量数 / Embedding 模型名（含 pill 标签：份数 / 版本号 / 同步状态 / prod）
3. **`.kb-section` 知识源管理**：左右两栏 `.kb-uploads` —— Manifest dropzone（单文件 YAML）+ 规则源文档 dropzone（多文件 PDF/DOCX/HTML，列出已上传文件 + size + 时间戳）
4. **`.kb-section` 已索引规则**：`.kb-rules` 表头 + 多行（规则编号 / 名称+副标题 / `chip-type`+色点 / chunks 数 / 最近检索时间）

样式 token 沿用 #3 已抽 `tokens.css` + `shell.css`，page-specific 样式（`.kb-mc` `.kb-rules` `.kb-dz` `.adm-hd` `.cta-dark` `.cta-pearl`）抽到 `admin-kb.css`。

---

## 4. API 调用（用 #3 §4.5 已封装 `api.knowledge.*`）

- `api.knowledge.status()` → metric 4 卡（source_count / chunk_count / vector_count / embedding_model）
- `api.knowledge.chunks()` → 已索引规则列表（每行 rule_id / name / type / chunk_count / last_query_at）
- `api.knowledge.uploadPack(manifestFile, sourceFiles)` → 「上传官方知识源文档」按钮触发 multipart
- `api.knowledge.clear()` → 「清空知识库」**双确认 modal**（第一次 confirm「确定要清空？」→ 第二次输入框输入「CLEAR」字样匹配后才放行）→ 调用 → 完成后刷新 metric + 列表
- `api.knowledge.importDemoPack()` → 演示场景兜底（如果当前 chunk_count===0，metric 区下方显示一行小字 hint「演示快速导入」link）

**不要**新增后端 endpoint，全部用 #3 已封装的客户端方法。

---

## 5. Anti-vision（严格遵守）

1. 只碰 `backend/app/static/pages/admin-kb/` 内 3 个新文件，**不动** `static/` 其他目录、不动 `js/router.js` `js/api.js` `js/shell.js` `css/tokens.css` `css/shell.css`
2. 不碰任何 `.py` / 后端代码 / 测试
3. **不要在这页放任何流程节点 / RAG 链路 / Agent 分支 / TopK / Rerank / 流程回放** —— 那些是 HANDOFF #4e（`#/admin/cases/:id/trace` 审查回放）的事
4. 「清空知识库」必须双确认 modal —— 演示场景误点损失大
5. 不引入框架 / 打包器 / npm 依赖，沿用原生 ES Modules
6. 不要从设计稿复制 `.caption` / 外层 `<style>` / `.frame` / `.gnav` / `.side` 那些壳级结构 —— 壳是 #3 全局做好的，本页只填 `#route-outlet` 内部

---

## 6. 验收 smoke

- [ ] 浏览器 `http://127.0.0.1:8888/#/admin/kb` 渲染 4 张 metric 卡 + 3 个 Pill 按钮 + 知识源管理 + 已索引规则列表
- [ ] metric 数字来自真实 `GET /chemical/knowledge/status`（不是 mock 硬编码），网络面板可见请求
- [ ] 「上传官方知识源文档」打开 modal，选 manifest YAML + 多个源文档后 POST 成功（如后端 endpoint 已存在）
- [ ] 「清空知识库」触发双确认 → 调用 `api.knowledge.clear()` → metric 与列表自动刷新
- [ ] `localStorage.setItem("role","client")` 后访问 `#/admin/kb`，立刻被重定向到 `#/cases`
- [ ] 控制台无 error，无 404，无 CORS 报错

---

## 7. 完成后回传

### 7.1 · `IMPLEMENTATION_LOG.md` 顶部追加

```markdown
## 任务 #3d · 2026-05-13 HH:MM · UI Phase 2d Admin 知识库工作台

**完成 / Done**
- 新建 pages/admin-kb/{index.js, admin-kb.html, admin-kb.css}
- 接入 api.knowledge.{status, chunks, uploadPack, clear, importDemoPack}
- 双确认 modal + 非管理员重定向守卫

**决策 / Decisions**
- 清空按钮选 cta-dark 而非 status-block 红，理由是 ...
- 双确认实现选择（confirm vs 输入框匹配），理由是 ...

**阻塞 / Blockers**：无 / 或具体描述
```

### 7.2 · 踩坑 → `NEW_TRAPS.md` 顶部追加

特别关注：multipart 上传在 FastAPI StaticFiles 模式下的 Content-Type 边界、`localStorage.role` 在 hashchange 时机的读取顺序、metric 卡数字为 0 时的空态文案。

---

## 8. 边界

- 不要 git commit / push / 建分支
- 不要访问 Windows `E:/AI/Mulit-agents/`
- HANDOFF 范围内自相矛盾 → 写 Blocker 停手等用户

---

**OrbitOS 签名**：徐钰 / OrbitOS Agent · 2026-05-13 · 决策依据 [[化工合规RAG工具#D45]]
