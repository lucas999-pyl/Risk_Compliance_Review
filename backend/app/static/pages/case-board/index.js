// case-board/index.js — Phase 2a · #/cases 看板页模块
//
// 协议：shell.js 通过 dynamic import 加载本模块并调用 mount(outlet, params)。
// 本模块不自己 registerRoute（shell.js 的 PAGE_MAP 已在全局注册）。
//
// 数据：api.cases.list() → { cases: [{id, title, status, latest_verdict,
//                            target_markets, review_scenario, check_types,
//                            material_type, intended_use, created_at,
//                            document_count, ...}] }
//
// 跳转：
//   新建 Case CTA / 末位 dashed 卡 → #/cases/new?step=1
//   卡片整体 + 底部链接 → 已完成走 #/cases/:id（报告），其余走 #/cases/:id/new?step=N

import { api } from "/static/js/api.js";
import { navigate } from "/static/js/router.js";

// 同源相对路径：CSS / template 与 index.js 同目录
const BASE = "/static/pages/case-board/";
const CSS_HREF = BASE + "case-board.css";
const TPL_URL = BASE + "case-board.html";

let cssInjected = false;
let templateText = null;

async function ensureAssets() {
  if (!cssInjected) {
    const exists = document.querySelector(`link[data-cb-css]`);
    if (!exists) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = CSS_HREF;
      link.dataset.cbCss = "1";
      document.head.appendChild(link);
    }
    cssInjected = true;
  }
  if (templateText === null) {
    const resp = await fetch(TPL_URL, { cache: "no-cache" });
    if (!resp.ok) throw new Error(`模板加载失败 ${resp.status}: ${TPL_URL}`);
    templateText = await resp.text();
  }
  return templateText;
}

// —— 状态映射（HANDOFF §5；后端无 phase/next_step，按 latest_verdict + status 推断） —— //

function mapCardStatus(c) {
  const v = (c.latest_verdict || "").toLowerCase();
  const status = (c.status || "").toLowerCase();

  if (v === "pass" || v === "ready_for_next_step") {
    return {
      bucket: "done",
      dot: "pass",
      // "可进入下一步" 客户读不懂；改为强调报告就绪
      text: "已完成 · 报告就绪",
      linkText: "查看报告 →",
      target: `#/cases/${encodeURIComponent(c.id)}`,
    };
  }
  if (v === "needs_review") {
    return {
      bucket: "done",
      dot: "warn",
      text: "需复核 · 报告就绪",
      linkText: "查看报告 →",
      target: `#/cases/${encodeURIComponent(c.id)}`,
    };
  }
  if (v === "needs_supplement") {
    return {
      bucket: "in_progress",
      dot: "block",
      text: "缺件 · 待补资料",
      linkText: "补件 →",
      target: `#/cases/${encodeURIComponent(c.id)}/new?step=2`,
    };
  }
  if (v === "not_approved") {
    return {
      bucket: "done",
      dot: "block",
      text: "未通过 · 报告就绪",
      linkText: "查看报告 →",
      target: `#/cases/${encodeURIComponent(c.id)}`,
    };
  }
  // draft / 无 verdict → 进行中（无 phase/next_step 字段，默认 step=1）
  return {
    bucket: "in_progress",
    dot: "mute",
    text: status === "draft" ? "Step 1 · 案件基本信息" : "进行中",
    linkText: "继续 →",
    target: `#/cases/${encodeURIComponent(c.id)}/new?step=1`,
  };
}

// —— chips：基于后端可用字段拼 3-4 个轻量信息片（材料 / 市场 / 检查项） —— //

function buildChips(c) {
  const chips = [];
  const mt = c.material_type || "";
  if (mt) {
    chips.push({ dot: "mute", text: `类型 ${escapeHtml(mt)}` });
  }
  const markets = Array.isArray(c.target_markets) ? c.target_markets : [];
  if (markets.length) {
    chips.push({ dot: "pass", text: `市场 ${markets.map(escapeHtml).join(" · ")}` });
  }
  const checks = Array.isArray(c.check_types) ? c.check_types : [];
  if (checks.length) {
    chips.push({ dot: "pass", text: `检查 ${checks.length}` });
  } else {
    chips.push({ dot: "mute", text: "检查 —" });
  }
  const docs = Number(c.document_count || 0);
  chips.push({ dot: docs > 0 ? "pass" : "mute", text: `文档 ${docs}` });
  return chips;
}

// —— 卡片渲染 —— //

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function formatCreatedAt(raw) {
  if (!raw) return "";
  // raw 可能是 ISO 字符串 / 带时区 / sqlite TEXT；只取 MM-DD
  try {
    const d = new Date(raw);
    if (!Number.isNaN(d.getTime())) {
      const mm = String(d.getMonth() + 1).padStart(2, "0");
      const dd = String(d.getDate()).padStart(2, "0");
      return `创建于 ${mm}-${dd}`;
    }
  } catch (_) { /* fallthrough */ }
  return `创建于 ${escapeHtml(String(raw).slice(0, 10))}`;
}

function shortId(id) {
  if (!id) return "";
  const s = String(id);
  if (s.length <= 16) return s;
  return s.slice(0, 8) + "…" + s.slice(-4);
}

function reviewScenarioLabel(scn) {
  const map = {
    market_access: "市场准入审查",
    formula_compliance: "配方合规",
    sds_review: "安全技术说明书复核",
  };
  return map[scn] || (scn || "合规审查");
}

function renderCard(c) {
  const st = mapCardStatus(c);
  const chips = buildChips(c)
    .map((ch) => `<span class="chip"><span class="dot ${ch.dot}"></span>${ch.text}</span>`)
    .join("");
  const metaParts = [];
  metaParts.push(reviewScenarioLabel(c.review_scenario));
  const markets = Array.isArray(c.target_markets) ? c.target_markets : [];
  if (markets.length) metaParts.push(`目标市场 ${markets.map(escapeHtml).join(" · ")}`);

  return `
    <article class="cb-card" role="button" tabindex="0" data-target="${escapeHtml(st.target)}">
      <div class="cap"><span>${escapeHtml(shortId(c.id))}</span><span>${escapeHtml(formatCreatedAt(c.created_at))}</span></div>
      <h3>${escapeHtml(c.title || "(未命名 Case)")}</h3>
      <div class="meta">${metaParts.map(escapeHtml).join(" · ")}</div>
      <div class="chips">${chips}</div>
      <div class="foot">
        <div class="status"><span class="dot ${st.dot}"></span>${escapeHtml(st.text)}</div>
        <span class="link" data-target="${escapeHtml(st.target)}">${escapeHtml(st.linkText)}</span>
        <button class="cb-delete" type="button" data-action="delete-case" data-case-id="${escapeHtml(c.id)}" title="删除 Case">删除</button>
      </div>
    </article>
  `;
}

function renderEmptyTrailingCard() {
  return `
    <button class="cb-card empty" type="button" data-target="#/cases/new?step=1">
      <div class="big">＋</div>
      <div class="lab">新建一个 Case，从案件基本信息开始</div>
    </button>
  `;
}

// —— 视图状态 —— //

const view = {
  cases: [],
  filter: "all",
  query: "",
};

function applyFilter(cases) {
  let list = cases.slice();
  if (view.query) {
    const q = view.query.toLowerCase();
    list = list.filter((c) => {
      const hay = `${c.title || ""} ${c.id || ""}`.toLowerCase();
      return hay.includes(q);
    });
  }
  if (view.filter !== "all") {
    list = list.filter((c) => {
      const bucket = mapCardStatus(c).bucket;
      if (view.filter === "in_progress") return bucket === "in_progress";
      if (view.filter === "done") return bucket === "done";
      if (view.filter === "needs_rerun") return false; // 无字段佐证，先返回空集
      return true;
    });
  }
  return list;
}

function paintGrid(root) {
  const grid = root.querySelector('[data-cb="grid"]');
  if (!grid) return;
  const visible = applyFilter(view.cases);

  // 计数 + lead
  const lead = root.querySelector('[data-cb="lead"]');
  const countEl = root.querySelector('[data-cb="count"]');
  const total = view.cases.length;
  const inProg = view.cases.filter((c) => mapCardStatus(c).bucket === "in_progress").length;
  if (lead) {
    lead.textContent = total
      ? `${total} 个 Case · ${inProg} 进行中`
      : `还没有 Case`;
  }
  if (countEl) {
    countEl.innerHTML = `<b>${total}</b> Case · <b>${inProg}</b> 进行中`;
  }

  // 空态（库存为 0）
  if (total === 0) {
    grid.outerHTML = `<div class="cb-empty-wrap" data-cb="empty"><div class="inner">还没有 Case，从右上角"新建 Case"开始</div></div>`;
    return;
  }

  // 有 Case 但当前筛选 / 搜索过滤后为空
  if (visible.length === 0) {
    grid.innerHTML = `
      <div style="grid-column:1 / -1;padding:48px 0;text-align:center;color:var(--ink-48);font-size:15px;">
        没有匹配当前筛选条件的 Case
      </div>
      ${renderEmptyTrailingCard()}
    `;
    return;
  }

  grid.innerHTML = visible.map(renderCard).join("") + renderEmptyTrailingCard();
}

// —— 事件绑定 —— //

function bindEvents(root) {
  // 新建 Case CTA
  const newBtn = root.querySelector('[data-cb="new"]');
  if (newBtn) {
    newBtn.addEventListener("click", () => navigate("#/cases/new?step=1"));
  }

  // 卡片 + 占位卡：事件委托
  root.addEventListener("click", async (e) => {
    const deleteBtn = e.target.closest('[data-action="delete-case"]');
    if (deleteBtn && root.contains(deleteBtn)) {
      e.preventDefault();
      e.stopPropagation();
      const caseId = deleteBtn.getAttribute("data-case-id");
      if (!caseId) return;
      if (!confirm(`确定删除 Case ${caseId}？`)) return;
      deleteBtn.setAttribute("disabled", "disabled");
      try {
        await api.cases.deleteOne(caseId);
        view.cases = view.cases.filter((item) => item.id !== caseId);
        paintGrid(root);
        if (window.shell && window.shell.refreshCases) window.shell.refreshCases();
      } catch (err) {
        deleteBtn.removeAttribute("disabled");
        const slot = root.querySelector('[data-cb="error-slot"]');
        if (slot) slot.innerHTML = `<div class="cb-error">删除失败：${escapeHtml(err.message || String(err))}</div>`;
      }
      return;
    }

    const card = e.target.closest("[data-target]");
    if (!card || !root.contains(card)) return;
    const target = card.getAttribute("data-target");
    if (target) {
      e.preventDefault();
      navigate(target);
    }
  });

  root.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const card = e.target.closest(".cb-card[data-target]");
    if (!card || !root.contains(card)) return;
    e.preventDefault();
    navigate(card.getAttribute("data-target"));
  });

  // 筛选 tab
  const seg = root.querySelector('[data-cb="seg"]');
  if (seg) {
    seg.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-filter]");
      if (!btn) return;
      seg.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b === btn));
      view.filter = btn.dataset.filter || "all";
      paintGrid(root);
    });
  }

  // 搜索
  const search = root.querySelector('[data-cb="search"]');
  if (search) {
    let timer = null;
    search.addEventListener("input", (e) => {
      clearTimeout(timer);
      const val = e.target.value || "";
      timer = setTimeout(() => {
        view.query = val.trim();
        paintGrid(root);
      }, 120);
    });
  }
}

// —— mount —— //

export async function mount(outlet, _params) {
  // shell 全局：当前页不需要顶部进度条
  if (window.shell) {
    window.shell.hideProgress();
    window.shell.setStepbar("Case 看板", "", "");
    window.shell.setCrumb("<b>Case 看板</b>");
  }

  let tpl;
  try {
    tpl = await ensureAssets();
  } catch (err) {
    outlet.innerHTML = `<div style="padding:64px;color:var(--block);">页面资源加载失败：${err.message || err}</div>`;
    return;
  }

  outlet.innerHTML = `<div class="cb-page-root">${tpl}</div>`;
  const root = outlet.querySelector(".cb-page-root");

  bindEvents(root);

  // 拉数据
  try {
    const resp = await api.cases.list();
    view.cases = (resp && Array.isArray(resp.cases)) ? resp.cases : [];
  } catch (err) {
    view.cases = [];
    const slot = root.querySelector('[data-cb="error-slot"]');
    if (slot) {
      slot.innerHTML = `<div class="cb-error">Case 列表加载失败：${escapeHtml(err.message || String(err))}</div>`;
    }
  }

  paintGrid(root);
}

export default { mount };
