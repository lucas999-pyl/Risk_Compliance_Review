// shell.js — 全局壳挂载入口
//   - 注入 nav / sidebar 静态结构
//   - 监听 hashchange，按需 dynamic import 页模块
//   - 暴露 window.shell.setProgress / setStepbar / setCrumb / refreshCases
//   - 视角切换器（客户预审 / 管理端）只存 localStorage role；本轮不做后端鉴权

import { registerRoute, navigate, startRouter, getCurrentRoute } from "/static/js/router.js";
import { api } from "/static/js/api.js";

const PAGE_MAP = {
  "#/cases": { module: "/static/pages/case-board/index.js", label: "Case 看板" },
  "#/cases/new": { module: "/static/pages/wizard/index.js", label: "新建 Case" },
  "#/cases/:id": { module: "/static/pages/report/index.js", label: "报告" },
  "#/admin/kb": { module: "/static/pages/admin-kb/index.js", label: "知识库管理", adminOnly: true },
  "#/admin/cases/:id/trace": { module: "/static/pages/admin-trace/index.js", label: "审查回放", adminOnly: true },
};

const loaded = new Map();

async function loadPage(modulePath) {
  if (loaded.has(modulePath)) return loaded.get(modulePath);
  try {
    const mod = await import(modulePath);
    loaded.set(modulePath, mod);
    return mod;
  } catch (err) {
    console.warn(`[shell] page module not ready: ${modulePath}`, err);
    return null;
  }
}

function makeMountFn(routeKey, info) {
  return async (outlet, params) => {
    if (info.adminOnly && getRole() !== "admin") {
      outlet.innerHTML = `<div style="padding:64px 80px;">
        <h2 style="font-family:var(--font-display);font-size:28px;font-weight:600;margin-bottom:12px;">需要管理员视角</h2>
        <p style="color:var(--ink-48);margin-bottom:24px;">请在顶栏切换到「管理端」后访问此页。</p>
        <button class="cta-primary" onclick="window.shell.setRole('admin')">切到管理端</button>
      </div>`;
      return;
    }
    const mod = await loadPage(info.module);
    if (!mod || typeof mod.mount !== "function") {
      outlet.innerHTML = `<div style="padding:64px 80px;color:var(--ink-48);">
        <div style="font-family:var(--font-display);font-size:24px;color:var(--ink);margin-bottom:8px;">${info.label}</div>
        <div>页面模块尚未就绪：<code>${info.module}</code></div>
      </div>`;
      return;
    }
    await mod.mount(outlet, params || {});
  };
}

// —— 顶栏 / sidebar 结构 —— //

function renderNav() {
  const nav = document.getElementById("shell-nav");
  if (!nav) return;
  nav.innerHTML = `
    <span class="brand">化工合规 RAG 预审</span>
    <span class="crumb" id="shell-crumb"><b>工作台</b></span>
    <span class="spacer"></span>
    <div class="switch" id="shell-role-switch" role="tablist">
      <button data-role="client" type="button">客户预审</button>
      <button data-role="admin" type="button">管理端</button>
    </div>
    <span class="me">演示账号</span>
  `;
  const switcher = nav.querySelector("#shell-role-switch");
  switcher.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-role]");
    if (!btn) return;
    setRole(btn.dataset.role);
  });
  syncRoleButtons();
}

function renderStepbar() {
  // 默认 stepbar 一段提示文案，Wizard 等页可以 setStepbar 覆盖
  const sb = document.getElementById("shell-stepbar");
  if (!sb) return;
  sb.innerHTML = `<span class="lead" id="stepbar-lead">工作台</span>
    <span class="tasks" id="stepbar-tasks"></span>
    <span class="spacer"></span>
    <span class="right" id="stepbar-right"></span>`;
}

function renderPbar(step = 0, total = 4) {
  const pb = document.getElementById("shell-pbar");
  if (!pb) return;
  let html = "";
  for (let i = 0; i < total; i++) {
    let cls = "seg";
    if (i < step) cls += " done";
    else if (i === step) cls += " curr";
    html += `<span class="${cls}"></span>`;
  }
  pb.innerHTML = html;
}

async function refreshCases() {
  const side = document.getElementById("shell-side");
  if (!side) return;
  let cases = [];
  try {
    const resp = await api.cases.list();
    cases = (resp && resp.cases) || [];
  } catch (err) {
    side.innerHTML = `<h6>Cases</h6>
      <div style="color:var(--block);font-size:13px;padding:0 12px;">加载失败：${err.message || err}</div>`;
    return;
  }
  const currentHash = getCurrentRoute();
  const activeId = (currentHash.match(/^#\/(?:admin\/)?cases\/([^/?]+)/) || [])[1];
  const items = cases.map((c) => {
    const id = c.id;
    const title = c.title || "(未命名)";
    const verdictDot = mapVerdictDot(c.latest_verdict || c.status);
    const subText = mapStatusLabel(c.status, c.latest_verdict);
    const isActive = id === activeId ? "active" : "";
    return `<a class="case-item ${isActive}" href="#/cases/${encodeURIComponent(id)}" data-case-id="${id}">
      <span class="title">${escapeHtml(title)}</span>
      <span class="sub"><span class="dot ${verdictDot}"></span>${escapeHtml(subText)}</span>
    </a>`;
  });
  side.innerHTML = `<h6>Cases</h6>
    <a class="case-item" href="#/admin/kb" style="background:var(--canvas);border:1px solid var(--hairline);">
      <span class="title">知识库管理</span>
      <span class="sub"><span class="dot pass"></span>RAG · 规则源 · 向量检索</span>
    </a>
    <a class="case-item" href="#/cases/new?step=1" style="background:var(--canvas);border:1px dashed var(--hairline);">
      <span class="title">＋ 新建 Case</span>
      <span class="sub" style="color:var(--ink-48);">Wizard 5 步</span>
    </a>
    ${items.join("") || `<div style="color:var(--ink-48);font-size:13px;padding:0 12px;">暂无 Case</div>`}`;
}

function mapVerdictDot(v) {
  switch ((v || "").toLowerCase()) {
    case "pass":
    case "ready_for_next_step":
      return "pass";
    case "needs_supplement":
    case "needs_review":
      return "warn";
    case "not_approved":
      return "block";
    default:
      return "mute";
  }
}

function mapStatusLabel(status, verdict) {
  if (verdict === "pass") return "通过";
  if (verdict === "needs_supplement") return "需补件";
  if (verdict === "needs_review") return "需复核";
  if (verdict === "not_approved") return "未通过";
  if (status === "draft") return "草稿";
  return status || "—";
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// —— role —— //

function getRole() {
  return localStorage.getItem("rcr.role") || "client";
}

function setRole(role) {
  if (role !== "admin" && role !== "client") role = "client";
  localStorage.setItem("rcr.role", role);
  syncRoleButtons();
  // 若当前在 admin-only 路由但切回 client，跳回 #/cases
  if (role === "client" && /^#\/admin\//.test(getCurrentRoute())) {
    navigate("#/cases");
  } else {
    // 重新派发当前路由（让 admin-only 页面更新闸门）
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  }
}

function syncRoleButtons() {
  const role = getRole();
  document.querySelectorAll("#shell-role-switch button[data-role]").forEach((btn) => {
    btn.classList.toggle("on", btn.dataset.role === role);
  });
}

// —— 暴露 API —— //

window.shell = {
  setProgress: (step, total = 4) => renderPbar(step, total),
  hideProgress: () => {
    const pb = document.getElementById("shell-pbar");
    if (pb) pb.innerHTML = "";
  },
  setStepbar: (text, tasksHTML = "", rightHTML = "") => {
    const lead = document.getElementById("stepbar-lead");
    const tasks = document.getElementById("stepbar-tasks");
    const right = document.getElementById("stepbar-right");
    if (lead) lead.textContent = text || "";
    if (tasks) tasks.innerHTML = tasksHTML;
    if (right) right.innerHTML = rightHTML;
  },
  setCrumb: (html) => {
    const cb = document.getElementById("shell-crumb");
    if (cb) cb.innerHTML = html;
  },
  refreshCases,
  getRole,
  setRole,
  navigate,
  api,
};

// —— boot —— //

document.addEventListener("DOMContentLoaded", () => {
  renderNav();
  renderStepbar();
  renderPbar(0, 4);

  for (const [pattern, info] of Object.entries(PAGE_MAP)) {
    registerRoute(pattern, makeMountFn(pattern, info));
  }

  // 默认进 Case 看板
  if (!window.location.hash || window.location.hash === "#" || window.location.hash === "#/") {
    window.location.hash = "#/cases";
  }

  startRouter();
  refreshCases();

  // 路由变化时同步 sidebar 高亮
  window.addEventListener("router:changed", () => {
    refreshCases();
  });
});
