// steps.js — Wizard 5 屏 renderStepN(outlet, ctx)。
// ctx 由 index.js 维护：{ caseId, draft, precheck, scope, runState }。
// 每屏统一：调用 shell.setProgress / setStepbar；只渲染主区（.wzbody + .wzfoot）。

import { api } from "/static/js/api.js";
import { navigate } from "/static/js/router.js";
import { uploadAndPrecheck, loadPrecheck, metricsFromPrecheck, statusLabel } from "./precheck.js";
import { runReview, SUB_TASKS } from "./runner.js";

// 4 段 pbar（与 sub-Agent A 保持一致）；step=1..5 → idx=0..4
function setShell(stepNum, leadTxt, tasksHTML, rightTxt) {
  if (window.shell && window.shell.setProgress) window.shell.setProgress(stepNum - 1, 4);
  if (window.shell && window.shell.setStepbar) window.shell.setStepbar(leadTxt, tasksHTML, rightTxt || "");
  if (window.shell && window.shell.setCrumb) {
    window.shell.setCrumb(`<b>新建 Case · Step ${stepNum} / 5</b>`);
  }
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function fmtSize(bytes) {
  if (!bytes && bytes !== 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function fileIcon(filename) {
  const ext = (String(filename || "").split(".").pop() || "").toLowerCase();
  if (["pdf"].includes(ext)) return "PDF";
  if (["xls", "xlsx", "csv"].includes(ext)) return "XLS";
  if (["doc", "docx"].includes(ext)) return "DOC";
  if (["png", "jpg", "jpeg", "gif", "webp"].includes(ext)) return "IMG";
  if (["txt", "md"].includes(ext)) return "TXT";
  return "DOC";
}

// 通用：渲染 wzfoot
function renderFoot({ backLabel, backHref, tip, nextLabel, nextDisabled, nextId, exitHref }) {
  const left = backLabel
    ? `<button class="cta-pearl" data-action="back" data-href="${backHref || ""}">${escapeHtml(backLabel)}</button>`
    : `<a class="link" href="${exitHref || "#/cases"}">← 退出 Wizard</a>`;
  const next = nextLabel
    ? `<button class="cta-primary${nextDisabled ? " disabled" : ""}" ${nextDisabled ? "disabled" : ""} id="${nextId || "wz-next"}">${escapeHtml(nextLabel)}</button>`
    : "";
  return `<div class="wzfoot">
    ${left}
    <div class="step-tag">${escapeHtml(tip || "")}</div>
    ${next}
  </div>`;
}

// 监听 wzfoot 通用「上一步」按钮
function wireFootBack(root) {
  const back = root.querySelector('[data-action="back"]');
  if (back) {
    back.addEventListener("click", () => {
      const href = back.getAttribute("data-href");
      if (href) navigate(href);
    });
  }
}

// ============================== Step 1 ==============================

const SCENARIOS = [
  { id: "market_access",        label: "市场准入预审（新产品上市前合规扫描）" },
  { id: "substitution",         label: "替代物料评估（配方变更 / 原料替换）" },
  { id: "supplier_intake",      label: "供应商资料准入（安全技术说明书 / 资质核验）" },
  { id: "process_introduction", label: "工艺导入风险评估" },
];

const MARKETS = [
  { id: "CN", label: "中国大陆" },
  { id: "EU", label: "欧盟（化学品法规 / 分类标签法规）" },
  { id: "US", label: "美国（化学品清单）" },
  { id: "KR", label: "韩国（化学品注册评估法规）" },
  { id: "JP", label: "日本（化审法）" },
];

export async function renderStep1(outlet, ctx) {
  const d = ctx.draft;
  setShell(1, "Step 1 · 案件基本信息",
    `<span class="curr">填写标题</span><span>选择场景</span><span>选择市场</span>`,
    "1 / 5",
  );
  outlet.innerHTML = `
    <div class="wzbody">
      <h1>新建审查 Case</h1>
      <div class="lead">先告诉系统这次预审的基本情景，让推荐审查项更贴合你的产品。</div>
      <section>
        <div class="field">
          <label>案件标题</label>
          <div class="hint">用一句话概括产品 + 用途，便于将来在 Case 列表中识别。</div>
          <input type="text" id="wz-title" value="${escapeHtml(d.title || "")}" placeholder="例如：某丙烯酸酯水性涂料 · 出口欧盟登记" />
        </div>
        <div class="field">
          <label>审查场景</label>
          <div class="hint">不同场景会触发不同规则库与必检项。</div>
          <div class="select"><select id="wz-scenario">
            ${SCENARIOS.map((s) => `<option value="${s.id}" ${s.id === d.scenario ? "selected" : ""}>${escapeHtml(s.label)}</option>`).join("")}
          </select></div>
        </div>
        <div class="field">
          <label>目标市场（可多选）</label>
          <div class="hint">勾选要面向的法规辖区。</div>
          <div class="toggle-chips" id="wz-markets">
            ${MARKETS.map((m) => `<button type="button" class="toggle${d.markets.includes(m.id) ? " on" : ""}" data-mk="${m.id}">${escapeHtml(m.label)}</button>`).join("")}
          </div>
        </div>
      </section>
      <div id="wz-err"></div>
    </div>
    ${renderFoot({
      tip: "下一步将进入「上传资料包」",
      nextLabel: "下一步 →",
      nextDisabled: !(d.title && d.title.trim() && d.markets.length > 0),
      nextId: "wz-next1",
      exitHref: "#/cases",
    })}
  `;

  const titleInput = outlet.querySelector("#wz-title");
  const scenSel    = outlet.querySelector("#wz-scenario");
  const mkWrap     = outlet.querySelector("#wz-markets");
  const nextBtn    = outlet.querySelector("#wz-next1");

  function refreshEnable() {
    const ok = titleInput.value.trim().length > 0 && d.markets.length > 0;
    nextBtn.classList.toggle("disabled", !ok);
    if (ok) nextBtn.removeAttribute("disabled");
    else nextBtn.setAttribute("disabled", "disabled");
  }

  titleInput.addEventListener("input", () => { d.title = titleInput.value; refreshEnable(); });
  scenSel.addEventListener("change", () => { d.scenario = scenSel.value; });
  mkWrap.addEventListener("click", (e) => {
    const btn = e.target.closest("button.toggle");
    if (!btn) return;
    const id = btn.dataset.mk;
    const idx = d.markets.indexOf(id);
    if (idx >= 0) d.markets.splice(idx, 1); else d.markets.push(id);
    btn.classList.toggle("on");
    refreshEnable();
  });

  nextBtn.addEventListener("click", async () => {
    if (nextBtn.hasAttribute("disabled")) return;
    nextBtn.setAttribute("disabled", "disabled");
    nextBtn.classList.add("disabled");
    nextBtn.textContent = "创建中…";
    try {
      const scenLabel = (SCENARIOS.find((s) => s.id === d.scenario) || SCENARIOS[0]).label;
      const created = await api.cases.create({
        title: d.title.trim(),
        target_markets: d.markets,
        intended_use: scenLabel,
        review_scenario: d.scenario,
        check_types: [],
      });
      const newId = created && created.id;
      if (!newId) throw new Error("后端未返回 case id");
      ctx.caseId = newId;
      if (window.shell && window.shell.refreshCases) window.shell.refreshCases();
      navigate(`#/cases/${encodeURIComponent(newId)}/new?step=2`);
    } catch (err) {
      const eb = outlet.querySelector("#wz-err");
      if (eb) eb.innerHTML = `<div class="wz-error">创建失败：${escapeHtml(err.message || err)}</div>`;
      nextBtn.textContent = "下一步 →";
      nextBtn.removeAttribute("disabled");
      nextBtn.classList.remove("disabled");
    }
  });
}

// ============================== Step 2 ==============================

export async function renderStep2(outlet, ctx) {
  setShell(2, "Step 2 · 上传资料包",
    `<span class="done">填写标题</span><span class="curr">上传文件</span><span>自动预检</span>`,
    "2 / 5",
  );
  if (!ctx.caseId) {
    outlet.innerHTML = `<div class="wzbody"><h1>缺少 Case</h1>
      <div class="lead">未找到 Case ID，请先回到 Step 1 创建。</div>
      ${renderFoot({ exitHref: "#/cases/new?step=1", tip: "" })}</div>`;
    return;
  }

  outlet.innerHTML = `
    <div class="wzbody">
      <h1>上传资料包</h1>
      <div class="lead">把这次审查涉及的安全技术说明书、配方表、工艺说明等一并丢进来，系统会自动识别类型并预检完整性。</div>
      <section>
        <div class="dropzone" id="wz-dz">
          <div class="big">＋</div>
          <div class="t">拖拽文件到此区域</div>
          <div class="h">或点击选择 · 支持 PDF / Word / Excel / 图片 · 单文件 ≤ 50MB</div>
          <div class="actions">
            <button class="cta-primary" id="wz-pick">选择文件</button>
            <button class="cta-pearl" id="wz-skip" type="button" title="使用演示资料包跳过上传">跳过 · 使用演示资料</button>
          </div>
          <input type="file" id="wz-input" multiple style="display:none;" />
        </div>
        <div class="uplist" id="wz-list"></div>
        <div id="wz-err"></div>
      </section>
    </div>
    ${renderFoot({
      backLabel: "← 上一步",
      backHref: `#/cases/${encodeURIComponent(ctx.caseId)}/new?step=1`,
      tip: "所有文件就绪后自动进入预检",
      nextLabel: "下一步（自动跳转）",
      nextDisabled: true,
      nextId: "wz-next2",
    })}
  `;
  wireFootBack(outlet);

  const dz       = outlet.querySelector("#wz-dz");
  const pickBtn  = outlet.querySelector("#wz-pick");
  const skipBtn  = outlet.querySelector("#wz-skip");
  const input    = outlet.querySelector("#wz-input");
  const listEl   = outlet.querySelector("#wz-list");
  const errEl    = outlet.querySelector("#wz-err");
  const nextBtn  = outlet.querySelector("#wz-next2");

  // rows = { name,size,state,progress }
  let rows = [];

  function renderList() {
    listEl.innerHTML = rows.map((r, i) => `
      <div class="uprow" data-i="${i}">
        <span class="icon-doc">${escapeHtml(fileIcon(r.name))}</span>
        <div class="name">${escapeHtml(r.name)}<small>${escapeHtml(r.note || "")}</small></div>
        <div class="size">${escapeHtml(fmtSize(r.size))}</div>
        <div class="progressbar"><i style="width:${Math.max(0, Math.min(100, r.progress | 0))}%;"></i></div>
        <div class="state ${r.state === "done" ? "done" : r.state === "err" ? "err" : ""}">${escapeHtml(
          r.state === "done" ? "已识别 ✓" : r.state === "err" ? "失败" : r.state === "uploading" ? `上传中 · ${r.progress | 0}%` : "等待中"
        )}</div>
      </div>
    `).join("");
  }

  async function startUpload(files) {
    errEl.innerHTML = "";
    const fs = Array.from(files);
    if (fs.length === 0) return;
    rows = fs.map((f) => ({ name: f.name, size: f.size, state: "uploading", progress: 0, note: "" }));
    renderList();

    // 视觉模拟单行进度（fetch 不暴露 upload 进度时退化为线性进度）
    const tick = setInterval(() => {
      let any = false;
      rows.forEach((r) => {
        if (r.state === "uploading" && r.progress < 92) {
          r.progress = Math.min(92, r.progress + 6 + Math.random() * 10);
          any = true;
        }
      });
      if (any) renderList();
    }, 220);

    try {
      const result = await uploadAndPrecheck(ctx.caseId, fs);
      clearInterval(tick);
      // 把后端 documents 数组与本地 rows 做名字匹配，标 done
      const recogByName = new Map(((result.package_precheck && result.package_precheck.documents) || [])
        .map((d) => [d.filename, d]));
      rows.forEach((r) => {
        r.progress = 100;
        r.state = "done";
        const m = recogByName.get(r.name);
        if (m) r.note = `${m.detected_type_label || m.detected_type || "已识别"} · 置信 ${Math.round((m.confidence || 0) * 100)}%`;
        else r.note = "已上传";
      });
      renderList();
      ctx.precheck = result.package_precheck;
      ctx.documents = result.documents;
      if (window.shell && window.shell.refreshCases) window.shell.refreshCases();
      // 自动前进
      setTimeout(() => {
        navigate(`#/cases/${encodeURIComponent(ctx.caseId)}/new?step=3`);
      }, 400);
    } catch (err) {
      clearInterval(tick);
      rows.forEach((r) => { if (r.state === "uploading") r.state = "err"; });
      renderList();
      errEl.innerHTML = `<div class="wz-error">上传失败：${escapeHtml(err.message || err)}</div>`;
    }
  }

  pickBtn.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); input.click(); });
  input.addEventListener("change", () => { if (input.files && input.files.length) startUpload(input.files); });
  // 点击 dropzone 空白区域也打开文件选择
  dz.addEventListener("click", (e) => {
    if (e.target.closest("button") || e.target.tagName === "INPUT") return;
    input.click();
  });

  // drag & drop
  ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => {
    e.preventDefault(); e.stopPropagation(); dz.classList.add("dragover");
  }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => {
    e.preventDefault(); e.stopPropagation(); dz.classList.remove("dragover");
  }));
  dz.addEventListener("drop", (e) => {
    const dt = e.dataTransfer;
    if (dt && dt.files && dt.files.length) startUpload(dt.files);
  });

  // 跳过上传：直接尝试拿后端已存在 documents（如果用户重入）
  skipBtn.addEventListener("click", async () => {
    try {
      const pre = await loadPrecheck(ctx.caseId);
      if ((pre.documents || []).length > 0) {
        ctx.precheck = pre.package_precheck;
        ctx.documents = pre.documents;
        navigate(`#/cases/${encodeURIComponent(ctx.caseId)}/new?step=3`);
      } else {
        errEl.innerHTML = `<div class="wz-error">还没有任何已上传文件，无法跳过。请先选择文件。</div>`;
      }
    } catch (err) {
      errEl.innerHTML = `<div class="wz-error">读取失败：${escapeHtml(err.message || err)}</div>`;
    }
  });

  nextBtn.addEventListener("click", () => {
    // 一般是 disabled；防御：若用户重入且已有 precheck，允许手动前进
    if (ctx.precheck) navigate(`#/cases/${encodeURIComponent(ctx.caseId)}/new?step=3`);
  });
}

// ============================== Step 3 ==============================

export async function renderStep3(outlet, ctx) {
  setShell(3, "Step 3 · 资料包预检",
    `<span class="done">填写标题</span><span class="done">上传文件</span><span class="curr">识别 · 校验完整性</span>`,
    "3 / 5",
  );
  if (!ctx.caseId) {
    outlet.innerHTML = `<div class="wzbody"><h1>缺少 Case</h1>
      ${renderFoot({ exitHref: "#/cases/new?step=1", tip: "" })}</div>`;
    return;
  }

  // 若无内存 precheck（用户刷新或直接跳进来），先拉一次
  outlet.innerHTML = `<div class="wzbody"><h1>资料预检结论</h1>
    <div class="lead">正在加载预检结果…</div></div>`;
  try {
    if (!ctx.precheck) {
      const pre = await loadPrecheck(ctx.caseId);
      ctx.precheck = pre.package_precheck;
      ctx.documents = pre.documents;
    }
  } catch (err) {
    outlet.innerHTML = `<div class="wzbody"><h1>资料预检结论</h1>
      <div class="wz-error">读取失败：${escapeHtml(err.message || err)}</div>
      ${renderFoot({ backLabel: "← 上一步", backHref: `#/cases/${encodeURIComponent(ctx.caseId)}/new?step=2`, tip: "" })}</div>`;
    return;
  }

  const pre = ctx.precheck;
  if (!pre) {
    outlet.innerHTML = `<div class="wzbody"><h1>资料预检结论</h1>
      <div class="lead">尚未生成预检结果，请先在 Step 2 上传资料。</div>
      ${renderFoot({ backLabel: "← 上一步", backHref: `#/cases/${encodeURIComponent(ctx.caseId)}/new?step=2`, tip: "" })}</div>`;
    wireFootBack(outlet);
    return;
  }

  const m = metricsFromPrecheck(pre);
  const stat = statusLabel(pre);
  const blocked = (pre.blocked_checks || []);
  const limited = (pre.limited_checks || []);
  const supplements = (pre.supplement_actions || []);
  const isBlocked = stat.tone === "block" || blocked.length > 0 || limited.length > 0 || supplements.length > 0;
  const docs = pre.documents || [];

  outlet.innerHTML = `
    <div class="wzbody">
      <h1>资料预检结论</h1>
      <div class="lead">${escapeHtml(pre.user_message || "系统已识别全部文件类型并校验完整性；下方四张卡是这一步的产出。")}</div>

      <section>
        <div class="mc-grid">
          <div class="mc">
            <div class="lab"><span class="dot lg pass"></span>已识别</div>
            <div class="num">${m.recognized}</div>
            <div class="desc">类型识别完成的文件数</div>
          </div>
          <div class="mc">
            <div class="lab"><span class="dot lg ${m.missing > 0 ? "warn" : "mute"}"></span>需补件</div>
            <div class="num ${m.missing > 0 ? "" : "mute"}">${m.missing}</div>
            <div class="desc">${m.missing > 0 ? escapeHtml((pre.missing_documents || []).join(" · ")) : "本场景下所需文件类型已齐"}</div>
          </div>
          <div class="mc">
            <div class="lab"><span class="dot lg pass"></span>可直接检查</div>
            <div class="num">${m.ready}</div>
            <div class="desc">${escapeHtml((pre.available_checks || []).slice(0, 4).map((c) => c.label || c.id || c).join(" · ")) || "—"}</div>
          </div>
          <div class="mc">
            <div class="lab"><span class="dot lg ${m.blocked > 0 ? "block" : "mute"}"></span>受限阻断</div>
            <div class="num ${m.blocked > 0 ? "" : "mute"}">${m.blocked}</div>
            <div class="desc">${m.blocked > 0 ? "见下方提示" : "无阻断项"}</div>
          </div>
        </div>
      </section>

      <section>
        <h3 style="font-size:14px;font-weight:600;color:var(--ink-48);letter-spacing:-0.224px;margin-bottom:12px;">已上传文件 · 识别结果</h3>
        <div style="background:var(--canvas);border:1px solid var(--hairline);border-radius:18px;overflow:hidden;">
          ${docs.length === 0 ? `<div style="padding:18px;color:var(--ink-48);font-size:14px;">无上传文件。</div>` : docs.map((d) => `
            <div class="file-ident">
              <span class="icon-doc">${escapeHtml(fileIcon(d.filename))}</span>
              <div>
                <div class="name">${escapeHtml(d.filename || "(未命名)")}</div>
                <div class="desc">${escapeHtml(d.detected_type_label || d.detected_type || "—")}</div>
              </div>
              <span class="chip strong">类型 · ${escapeHtml(d.detected_type_label || d.detected_type || "未知")}</span>
              <div class="pct">置信 ${Math.round((d.confidence || 0) * 100)}%</div>
              <div class="desc">${escapeHtml(d.user_message || "—")}</div>
            </div>
          `).join("")}
        </div>
      </section>

      ${isBlocked ? `
      <section>
        <div class="alert-card">
          <div class="head"><span class="dot lg ${stat.tone === "block" ? "block" : "warn"}"></span>${escapeHtml(stat.text)}</div>
          <ul>
            ${supplements.map((s) => `<li><b>${escapeHtml(s.title || s.id || "建议")}</b> ｜ ${escapeHtml(s.description || s.detail || "")}</li>`).join("")
              || blocked.map((b) => `<li><b>${escapeHtml(b.label || b.id || b)}</b> ｜ 该项在当前资料下被判定为受限/阻断。</li>`).join("")
              || limited.map((b) => `<li><b>${escapeHtml(b.label || b.id || b)}</b> ｜ 该项可继续，但报告会标记。</li>`).join("")
            }
          </ul>
          <div class="act">
            <button class="cta-pearl" data-action="back" data-href="#/cases/${encodeURIComponent(ctx.caseId)}/new?step=2">上传补件</button>
          </div>
        </div>
      </section>` : ""}
    </div>
    ${renderFoot({
      backLabel: "← 上一步",
      backHref: `#/cases/${encodeURIComponent(ctx.caseId)}/new?step=2`,
      tip: isBlocked ? "已知悉阻断项后仍可继续，将在报告中标记" : "数据齐备，可进入下一步",
      nextLabel: isBlocked ? "已知悉，继续 →" : "下一步 · 选择审查范围 →",
      nextId: "wz-next3",
    })}
  `;
  wireFootBack(outlet);
  outlet.querySelectorAll('[data-action="back"]').forEach((b) => {
    b.addEventListener("click", () => {
      const href = b.getAttribute("data-href");
      if (href) navigate(href);
    });
  });
  const n = outlet.querySelector("#wz-next3");
  if (n) n.addEventListener("click", () => navigate(`#/cases/${encodeURIComponent(ctx.caseId)}/new?step=4`));
}

// ============================== Step 4 ==============================
// 18 项设计稿对应 4 大类。本实现把后端 10 个 check_type 映射到 4 组，
// 并补 8 项"演示项"（仅前端显示，不影响后端运行）以贴合设计稿计数。
// 用户调整勾选实时反映到 stepbar；前进时 ctx.scope 保留选择。

const SCOPE_GROUPS = [
  {
    key: "material", title: "物料", items: [
      { id: "ingredient_identity",   label: "组分清单与登记号一致性核对", sub: "所有声明的登记号在权威数据库可查验", rule: "GB/T 17519 · 第 3 条", real: true, recommended: true },
      { id: "restricted_substance",  label: "欧盟受限物质比对（化学品法规附录 XVII）", sub: "本场景必选 · 由目标市场触发", rule: "欧盟化学品法规附录 XVII", real: true, recommended: true },
      { id: "svhc_check",            label: "欧盟高度关注物质候选清单比对", sub: "对照最近一版高度关注物质名录", rule: "欧盟化学品法规第 59 条", real: false, recommended: true },
      { id: "iecsc_check",           label: "国内 IECSC 新化学物质名录核验", sub: "对国内已登记物质 / 新物质身份判定", rule: "化学物质环境管理办法", real: false, recommended: false },
      { id: "cmr_check",             label: "CMR · 致癌 / 致畸 / 生殖毒性筛查", sub: "CLP 第 36 条对应", rule: "CLP 附件 VI", real: false, recommended: false },
    ],
  },
  {
    key: "process", title: "工艺", items: [
      { id: "process_fit",           label: "工艺关键参数核查（温压 / 反应时长）", sub: "GB 13690 · 第 5.2 条对应项", rule: "GB 13690 · 第 5.2 条", real: true, recommended: true },
      { id: "voc_limit",             label: "挥发性有机化合物排放限值", sub: "水性涂料挥发性有机物 ≤ 80 g/L", rule: "GB 18582-2020", real: false, recommended: true },
      { id: "energy_footprint",      label: "能效与碳足迹估算（可选）", sub: "非合规必检，仅供参考", rule: "非强制", real: false, recommended: false },
    ],
  },
  {
    key: "storage", title: "储运", items: [
      { id: "storage_transport",     label: "运输分类与运输编号匹配", sub: "多式联运危险货物分类", rule: "JT/T 617 · 运输编号 1263", real: true, recommended: true },
      { id: "compatibility_risk",    label: "物料相容性 / 不相容物声明", sub: "安全技术说明书第 7 节 / 第 10 节", rule: "安全技术说明书第 7、10 节", real: true, recommended: true },
      { id: "sds_key_sections",      label: "包装标签分类要素完整性", sub: "象形图 / 信号词 / 危害与防范说明", rule: "全球统一分类和标签制度修订版 9", real: true, recommended: true },
      { id: "emergency_plan",        label: "应急响应 / 泄漏处置预案", sub: "安全技术说明书第 6 节", rule: "安全技术说明书第 6 节", real: false, recommended: false },
    ],
  },
  {
    key: "regulatory", title: "法规适配", items: [
      { id: "regulatory_screening",  label: "目标市场法规匹配（欧盟/美国/中国等）", sub: "欧盟化学品法规 / 美国化学品清单 / 国内目录联合筛查", rule: "欧盟化学品法规第 5、6 条", real: true, recommended: true },
      { id: "supplier_evidence_consistency", label: "供应商声明 / 检测报告一致性", sub: "下游用户告知义务与一致性", rule: "欧盟化学品法规第 31、38 条", real: true, recommended: true },
      { id: "intake_readiness",      label: "资料完整性与可审性", sub: "判断是否具备进入正式审查的基线条件", rule: "内部 SOP", real: true, recommended: true },
      { id: "manual_review",         label: "人工复核与补件建议", sub: "由系统标注 → 人工把关", rule: "人工复核", real: true, recommended: true },
      { id: "label_lang",            label: "标签语言版本适配", sub: "欧盟成员国语言要求", rule: "分类标签法规第 17 条", real: false, recommended: false },
      { id: "tsca_check",            label: "美国化学品申报", sub: "未勾选美国时建议跳过", rule: "美国化学品清单第 5 节", real: false, recommended: false },
    ],
  },
];

function totalScopeCount() {
  return SCOPE_GROUPS.reduce((n, g) => n + g.items.length, 0);
}

export async function renderStep4(outlet, ctx) {
  if (!ctx.caseId) {
    outlet.innerHTML = `<div class="wzbody"><h1>缺少 Case</h1>
      ${renderFoot({ exitHref: "#/cases/new?step=1", tip: "" })}</div>`;
    return;
  }

  // 初始化 ctx.scope（一次性）：取所有 recommended 项
  if (!ctx.scope) {
    const initial = new Set();
    SCOPE_GROUPS.forEach((g) => g.items.forEach((it) => { if (it.recommended) initial.add(it.id); }));
    ctx.scope = initial;
  }
  const total = totalScopeCount();

  function updateStepbar() {
    setShell(4, "Step 4 · 审查范围",
      `<span class="done">填写标题</span><span class="done">上传文件</span><span class="done">预检完成</span><span class="curr">勾选审查项</span>`,
      `4 / 5 · 已选 ${ctx.scope.size} / 共 ${total}`,
    );
  }
  updateStepbar();

  const groupsHTML = SCOPE_GROUPS.map((g) => {
    const onCt = g.items.filter((it) => ctx.scope.has(it.id)).length;
    return `
      <div class="scope-group" data-group="${g.key}">
        <h3>${escapeHtml(g.title)} · ${g.items.length} 项
          <span class="ct">已选 <span class="g-on">${onCt}</span> / ${g.items.length} ·
            <a class="link" data-act="reset" data-g="${g.key}" href="javascript:void(0)">恢复推荐</a> ·
            <a class="link" data-act="none" data-g="${g.key}" href="javascript:void(0)">全不选</a>
          </span>
        </h3>
        ${g.items.map((it) => `
          <div class="scope-row${ctx.scope.has(it.id) ? " on" : ""}${it.recommended ? " recommended" : ""}" data-id="${it.id}">
            <span class="cb"></span>
            <div class="lbl">${escapeHtml(it.label)}<small>${escapeHtml(it.sub)}</small></div>
            <div class="rule">${escapeHtml(it.rule)}</div>
          </div>
        `).join("")}
      </div>`;
  }).join("");

  outlet.innerHTML = `
    <div class="wzbody">
      <h1>审查范围</h1>
      <div class="lead">系统根据场景与目标市场推荐了 ${SCOPE_GROUPS.reduce((n, g) => n + g.items.filter((i) => i.recommended).length, 0)} 项；你可以增删任意项，被勾选的项会进入 Step 5 的实际预审。</div>
      <section>${groupsHTML}</section>
    </div>
    ${renderFoot({
      backLabel: "← 上一步",
      backHref: `#/cases/${encodeURIComponent(ctx.caseId)}/new?step=3`,
      tip: `将以「已选 ${ctx.scope.size} 项」运行预审`,
      nextLabel: "下一步 · 运行预审 →",
      nextId: "wz-next4",
      nextDisabled: ctx.scope.size === 0,
    })}
  `;
  wireFootBack(outlet);

  function refreshGroupCounts() {
    SCOPE_GROUPS.forEach((g) => {
      const grpEl = outlet.querySelector(`.scope-group[data-group="${g.key}"]`);
      if (!grpEl) return;
      const onCt = g.items.filter((it) => ctx.scope.has(it.id)).length;
      const span = grpEl.querySelector(".g-on");
      if (span) span.textContent = onCt;
    });
    const foot = outlet.querySelector(".wzfoot .step-tag");
    if (foot) foot.textContent = `将以「已选 ${ctx.scope.size} 项」运行预审`;
    const nb = outlet.querySelector("#wz-next4");
    if (nb) {
      if (ctx.scope.size === 0) { nb.setAttribute("disabled", "disabled"); nb.classList.add("disabled"); }
      else { nb.removeAttribute("disabled"); nb.classList.remove("disabled"); }
    }
    updateStepbar();
  }

  outlet.querySelectorAll(".scope-row").forEach((row) => {
    row.addEventListener("click", () => {
      const id = row.dataset.id;
      if (ctx.scope.has(id)) { ctx.scope.delete(id); row.classList.remove("on"); }
      else { ctx.scope.add(id); row.classList.add("on"); }
      refreshGroupCounts();
    });
  });
  outlet.querySelectorAll('[data-act="reset"]').forEach((a) => {
    a.addEventListener("click", () => {
      const key = a.dataset.g;
      const grp = SCOPE_GROUPS.find((g) => g.key === key);
      if (!grp) return;
      grp.items.forEach((it) => {
        if (it.recommended) ctx.scope.add(it.id); else ctx.scope.delete(it.id);
      });
      // 重渲该组所有 row 的 on 状态
      outlet.querySelectorAll(`.scope-group[data-group="${key}"] .scope-row`).forEach((row) => {
        row.classList.toggle("on", ctx.scope.has(row.dataset.id));
      });
      refreshGroupCounts();
    });
  });
  outlet.querySelectorAll('[data-act="none"]').forEach((a) => {
    a.addEventListener("click", () => {
      const key = a.dataset.g;
      const grp = SCOPE_GROUPS.find((g) => g.key === key);
      if (!grp) return;
      grp.items.forEach((it) => ctx.scope.delete(it.id));
      outlet.querySelectorAll(`.scope-group[data-group="${key}"] .scope-row`).forEach((row) => row.classList.remove("on"));
      refreshGroupCounts();
    });
  });

  const nextBtn = outlet.querySelector("#wz-next4");
  nextBtn.addEventListener("click", () => {
    if (nextBtn.hasAttribute("disabled")) return;
    navigate(`#/cases/${encodeURIComponent(ctx.caseId)}/new?step=5&autoRunFromStep4=1`);
  });
}

// ============================== Step 5 ==============================

export async function renderStep5(outlet, ctx) {
  const autoRunFromStep4 = new URLSearchParams((window.location.hash.split("?")[1] || "")).get("autoRunFromStep4") === "1";
  setShell(5, "Step 5 · 运行预审",
    `<span class="done">填写标题</span><span class="done">上传文件</span><span class="done">预检完成</span><span class="done">范围确认</span><span class="curr">运行</span>`,
    "5 / 5",
  );
  if (!ctx.caseId) {
    outlet.innerHTML = `<div class="wzbody"><h1>缺少 Case</h1>
      ${renderFoot({ exitHref: "#/cases/new?step=1", tip: "" })}</div>`;
    return;
  }

  outlet.innerHTML = `
    <div class="wzbody">
      <h1>运行预审</h1>
      <div class="lead">系统正在按所选审查范围跑完整链路。完成后会自动跳到报告页 —— 你不需要在此等候。</div>
      <section id="wz-run-anchor" style="margin-top:32px;">
        <div style="display:flex;justify-content:center;padding:48px 0;">
          ${autoRunFromStep4
            ? `<span class="step-tag">自动开始预审...</span>`
            : `<button class="cta-primary lg" id="wz-run">运行预审</button>`}
        </div>
      </section>
      <section style="margin-top:24px;">
        <div style="font-size:13px;color:var(--ink-48);letter-spacing:-0.12px;">
          提示 · 运行期间可关闭本窗口，进度会在左侧 Case 列表小圆点回显；完成后此页会自动跳转报告页。
        </div>
      </section>
      <div id="wz-err"></div>
    </div>
    ${renderFoot({
      backLabel: "← 上一步",
      backHref: `#/cases/${encodeURIComponent(ctx.caseId)}/new?step=4`,
      tip: "完成后自动跳到报告页",
    })}
  `;
  wireFootBack(outlet);

  const anchor = outlet.querySelector("#wz-run-anchor");
  const runBtn = outlet.querySelector("#wz-run");
  const errEl  = outlet.querySelector("#wz-err");

  function drawCard(rows, pct) {
    anchor.innerHTML = `
      <div class="runcard">
        <div class="total">
          <div class="t">整体进度</div>
          <div class="pct">${pct}%</div>
        </div>
        <div class="bar"><i style="width:${pct}%;"></i></div>
        <div class="sub-h">子任务</div>
        ${rows.map((r) => {
          let dot = "";
          let cls = "mute";
          if (r.state === "done")    { dot = `<span class="dot lg pass"></span>`; cls = "done"; }
          else if (r.state === "running") { dot = `<span class="spinner"></span>`; cls = "curr"; }
          else if (r.state === "failed")  { dot = `<span class="dot lg block"></span>`; cls = "curr"; }
          else                           { dot = `<span class="dot lg mute"></span>`; cls = "mute"; }
          const st =
            r.state === "done" ? `<div class="st done">完成</div>`
            : r.state === "running" ? `<div class="st warn">进行中 · ${Math.round(r.elapsedMs / 1000)}s</div>`
            : r.state === "failed" ? `<div class="st err">失败 · <a class="link" href="javascript:void(0)" data-act="retry">重试</a></div>`
            : `<div class="st">待开始</div>`;
          return `<div class="row">${dot}<div class="n ${cls}">${escapeHtml(r.label)}</div>${st}</div>`;
        }).join("")}
      </div>
    `;
    const retry = anchor.querySelector('[data-act="retry"]');
    if (retry) retry.addEventListener("click", () => kickoff());
  }

  async function kickoff() {
    errEl.innerHTML = "";
    drawCard(SUB_TASKS.map((t) => ({ ...t, state: "pending", elapsedMs: 0 })), 0);
    try {
      const { cancelled } = await runReview(ctx.caseId, (rows, pct) => drawCard(rows, pct));
      if (cancelled) return;
      if (window.shell && window.shell.refreshCases) window.shell.refreshCases();
      // 完成后自动跳报告页
      setTimeout(() => navigate(`#/cases/${encodeURIComponent(ctx.caseId)}`), 500);
    } catch (err) {
      errEl.innerHTML = `<div class="wz-error">运行失败：${escapeHtml(err.message || err)}</div>`;
    }
  }

  if (autoRunFromStep4) kickoff();
  else if (runBtn) runBtn.addEventListener("click", () => kickoff());
}
