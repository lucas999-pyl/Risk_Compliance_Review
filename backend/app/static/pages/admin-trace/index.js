// admin-trace/index.js — Phase 2e · #/admin/cases/:id/trace 模块
//
// 协议：shell.js 通过 dynamic import 加载本模块并调用 mount(outlet, params)。
//   - params.id 为 Case ID
//   - 路由 adminOnly=true 由 shell.js 闸门兜底；本模块第一行再做一次防御性检查
// 数据：
//   - api.cases.get(id) → { case, latest_report }
//     latest_report.nodes = [{node_id,label,status,started_at,completed_at,input,output}, ...]
//   - api.cases.retrievalPreview(id) （可选）→ 当 latest_report 缺失时也能拉到 retrieval 字段
//
// 视图：顶部元信息条 + 左栏 10 节点时间线 + 右栏节点详情（4 折叠面板）。
// 不做实时 SSE 回放、不引框架、不写 emoji。

import { api } from "/static/js/api.js";
import { navigate } from "/static/js/router.js";

const BASE = "/static/pages/admin-trace/";
const CSS_HREF = BASE + "admin-trace.css";
const TPL_URL = BASE + "admin-trace.html";

let cssInjected = false;
let templateText = null;

async function ensureAssets() {
  if (!cssInjected) {
    if (!document.querySelector('link[data-trc-css]')) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = CSS_HREF;
      link.dataset.trcCss = "1";
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

// —— 工具 —— //

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function fmtDate(raw) {
  if (!raw) return "";
  try {
    const d = new Date(raw);
    if (!Number.isNaN(d.getTime())) {
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, "0");
      const dd = String(d.getDate()).padStart(2, "0");
      return `${y}-${m}-${dd}`;
    }
  } catch (_) {}
  return String(raw).slice(0, 10);
}

function durationSec(start, end) {
  if (!start || !end) return null;
  try {
    const ms = new Date(end).getTime() - new Date(start).getTime();
    if (!Number.isFinite(ms) || ms < 0) return null;
    return ms / 1000;
  } catch (_) { return null; }
}

function fmtDuration(sec) {
  if (sec == null) return "—";
  if (sec < 1) return `${Math.round(sec * 1000)}ms`;
  if (sec < 60) return `${sec.toFixed(sec < 10 ? 2 : 1)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function fmtBytes(n) {
  if (!Number.isFinite(n)) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

function safeJsonSize(obj) {
  try {
    const s = JSON.stringify(obj);
    return new Blob([s]).size;
  } catch (_) { return 0; }
}

function statusDot(status) {
  const s = String(status || "").toLowerCase();
  if (s === "completed" || s === "pass" || s === "ok" || s === "done") return "pass";
  if (s === "warn" || s === "needs_review" || s === "warning") return "warn";
  if (s === "error" || s === "failed" || s === "fail" || s === "block") return "block";
  if (s === "running" || s === "pending") return "warn";
  return "mute";
}

function statusIsRunning(status) {
  const s = String(status || "").toLowerCase();
  return s === "running" || s === "pending";
}

function verdictLabel(v) {
  if (!v) return "—";
  const s = String(v);
  if (/合规|pass/i.test(s)) return s;
  if (/复核|needs_review/i.test(s)) return s;
  if (/补/i.test(s)) return s;
  return s;
}

function verdictDot(v) {
  const s = String(v || "").toLowerCase();
  if (/合规|pass/.test(s)) return "pass";
  if (/复核|review/.test(s)) return "warn";
  if (/补|supplement/.test(s)) return "block";
  if (/未通过|not.?approved|block/.test(s)) return "block";
  return "mute";
}

function totalDurationSec(nodes) {
  if (!Array.isArray(nodes) || nodes.length === 0) return null;
  const starts = nodes.map((n) => n && n.started_at).filter(Boolean);
  const ends = nodes.map((n) => n && n.completed_at).filter(Boolean);
  if (!starts.length || !ends.length) return null;
  const s = Math.min(...starts.map((x) => new Date(x).getTime()));
  const e = Math.max(...ends.map((x) => new Date(x).getTime()));
  if (!Number.isFinite(s) || !Number.isFinite(e) || e < s) return null;
  return (e - s) / 1000;
}

// —— 元信息条 —— //

function renderMeta(root, ctx) {
  const { caseObj, report, nodes } = ctx;
  const caseId = caseObj.id || caseObj.case_id || ctx.caseId;
  const title = caseObj.title || report?.case_title || "审查回放";
  const scenarioMap = {
    market_access: "市场准入审查",
    formula_compliance: "配方合规",
    sds_review: "安全技术说明书复核",
  };
  const scenario = scenarioMap[caseObj.review_scenario] || caseObj.review_scenario || "合规审查";
  const markets = Array.isArray(caseObj.target_markets) ? caseObj.target_markets : [];
  const reviewDate = fmtDate(report?.generated_at || caseObj.created_at);
  const cap = `${escapeHtml(caseId)} · ${escapeHtml(scenario)}${markets.length ? " · " + markets.map(escapeHtml).join(" · ") : ""}${reviewDate ? " · 审查日期 " + escapeHtml(reviewDate) : ""}`;

  const total = totalDurationSec(nodes);
  const tokenUsage = report?.agent_orchestration?.token_usage || report?.token_usage || null;
  const subParts = [];
  subParts.push(`${nodes.length} 节点全链路 trace`);
  if (total != null) subParts.push(`总耗时 ${fmtDuration(total)}`);
  if (tokenUsage) {
    const tt = tokenUsage.total_tokens ?? tokenUsage.total ?? null;
    if (tt != null) subParts.push(`Token ${tt}`);
  } else {
    subParts.push("Token 用量见节点详情");
  }

  root.querySelector('[data-trc="meta-cap"]').innerHTML = cap;
  root.querySelector('[data-trc="title"]').textContent = `审查回放 · ${title}`;
  root.querySelector('[data-trc="meta-sub"]').textContent = subParts.join(" · ");

  // chips
  const findings = Array.isArray(report?.findings) ? report.findings : [];
  const evidences = Array.isArray(report?.evidences) ? report.evidences : [];
  const ruleHits = Array.isArray(report?.rule_hits) ? report.rule_hits : [];
  const blocks = findings.filter((f) => {
    const sev = String(f?.severity || f?.level || "").toLowerCase();
    return sev === "block" || sev === "high" || sev === "critical";
  }).length;
  const supplements = findings.filter((f) => {
    const sev = String(f?.severity || f?.level || "").toLowerCase();
    return sev === "needs_supplement" || sev === "warn" || sev === "medium";
  }).length;
  const verdict = report?.verdict;

  const chipsHtml = [
    `<span class="chip strong"><span class="dot pass"></span>已识别 ${ruleHits.length}</span>`,
    `<span class="chip strong"><span class="dot ${supplements ? "warn" : "mute"}"></span>需补 ${supplements}</span>`,
    `<span class="chip strong"><span class="dot pass"></span>可查 ${evidences.length}</span>`,
    `<span class="chip strong"><span class="dot ${blocks ? "block" : "mute"}"></span>阻断 ${blocks}</span>`,
    `<span class="chip strong"><span class="dot ${verdictDot(verdict)}"></span>结论 · ${escapeHtml(verdictLabel(verdict))}</span>`,
  ].join("");
  root.querySelector('[data-trc="chips"]').innerHTML = chipsHtml;
}

// —— 左栏时间线 —— //

function renderTimeline(root, ctx) {
  const tl = root.querySelector('[data-trc="timeline"]');
  if (!tl) return;
  const html = ctx.nodes.map((n, idx) => {
    const dot = statusDot(n.status);
    const running = statusIsRunning(n.status);
    const dur = durationSec(n.started_at, n.completed_at);
    const summary = nodeSummaryHint(n);
    const isActive = idx === ctx.activeIdx;
    return `
      <button class="trc-node ${isActive ? "active" : ""}" type="button" data-idx="${idx}">
        <div class="stem">
          <span class="dot ${dot}"></span>
          ${running ? '<span class="spinner" style="margin-left:-12px;margin-top:-2px;"></span>' : ""}
        </div>
        <div>
          <div class="nm">${escapeHtml(n.label || n.node_id || "节点 " + (idx + 1))}</div>
          <div class="meta">
            <span class="meta-l">${escapeHtml(summary)}</span>
            <span class="meta-r">${fmtDuration(dur)}</span>
          </div>
        </div>
      </button>
    `;
  }).join("");
  tl.innerHTML = html;
}

function nodeSummaryHint(n) {
  const out = n.output || {};
  switch (n.node_id) {
    case "load_task":
      return "Case 元数据初始化";
    case "parse_sds": {
      const sc = out.section_count;
      const miss = (out.missing_fields || []).filter((m) => m && m !== "无").length;
      return sc != null ? `${sc} 节段抽取${miss ? " · 缺 " + miss : ""}` : "解析安全技术说明书";
    }
    case "parse_formula": {
      const cc = out.component_count;
      return cc != null ? `${cc} 组分 + 登记号` : "解析配方表";
    }
    case "parse_process":
      return "解析工艺说明";
    case "rag_retrieve": {
      const rc = out.retrieved_chunk_count;
      const qc = (n.input || {}).agent_query_count;
      return `${qc != null ? "Q " + qc + " · " : ""}命中 ${rc ?? "—"} chunks`;
    }
    case "material_agent":
    case "process_agent":
    case "storage_agent":
    case "regulatory_agent":
      return `verdict · ${out.verdict || "—"}`;
    case "cross_check":
      return `分 ${out.score ?? "—"} · 冲突 ${(out.conflicts || []).length}`;
    case "chief_review":
      return `主审 · ${out?.chief_review?.verdict || out.verdict || "—"}`;
    default:
      return String(n.status || "");
  }
}

// —— 右栏节点详情 —— //

function renderDetail(root, ctx) {
  const n = ctx.nodes[ctx.activeIdx];
  if (!n) return;

  const ttl = root.querySelector('[data-trc="detail-ttl"]');
  const sub = root.querySelector('[data-trc="detail-sub"]');
  const panels = root.querySelector('[data-trc="panels"]');

  ttl.textContent = `${n.label || n.node_id} · 节点详情`;

  // sub 行 — 按节点类型组合
  const dur = durationSec(n.started_at, n.completed_at);
  const subParts = [`耗时 ${fmtDuration(dur)}`];
  subParts.push(`status · ${escapeHtml(n.status || "—")}`);
  const out = n.output || {};
  if (n.node_id === "rag_retrieve") {
    subParts.push(`查询数 ${(out.rag_queries && Object.keys(out.rag_queries).length) || (n.input || {}).agent_query_count || "—"}`);
    subParts.push(`TopK ${(n.input || {}).top_k_query ?? "—"}`);
    subParts.push(`命中 ${out.retrieved_chunk_count ?? "—"} chunks`);
  } else if (/_agent$/.test(n.node_id || "")) {
    subParts.push(`verdict ${out.verdict || "—"}`);
    subParts.push(`置信 ${out.confidence ?? "—"}`);
    subParts.push(`LLM ${out.llm_used ? (out.llm_model || "yes") : "no"}`);
  } else if (n.node_id === "cross_check") {
    subParts.push(`一致性分 ${out.score ?? "—"}`);
    subParts.push(`冲突 ${(out.conflicts || []).length}`);
  } else if (n.node_id === "chief_review") {
    const cr = out.chief_review || {};
    subParts.push(`verdict ${cr.verdict || "—"}`);
    subParts.push(`needs_human ${cr.needs_human ? "是" : "否"}`);
  }
  sub.innerHTML = subParts.map((p) => `<span>${typeof p === "string" ? p : escapeHtml(String(p))}</span>`).join("");

  // 4 个折叠面板
  panels.innerHTML = buildPanels(n, ctx);
}

function buildPanels(n, ctx) {
  const inputObj = n.input || {};
  const outputObj = n.output || {};

  // panel 1 — 查询构造（仅 rag_retrieve / agent 节点有意义；其余兜底）
  let p1 = "";
  if (n.node_id === "rag_retrieve") {
    const rq = outputObj.rag_queries || {};
    const entries = Object.entries(rq);
    if (entries.length) {
      const lines = entries.map(([agent, q], i) => `q${String(i + 1).padStart(2, "0")}  [${agent}] ${q}`).join("\n");
      p1 = `<pre>${escapeHtml(lines)}</pre>`;
    } else if (outputObj.query) {
      p1 = `<pre>${escapeHtml(outputObj.query)}</pre>`;
    }
  } else if (/_agent$/.test(n.node_id || "")) {
    if (outputObj.rag_query) {
      p1 = `<pre>${escapeHtml(outputObj.rag_query)}</pre>`;
    }
  }
  const p1Summary = n.node_id === "rag_retrieve"
    ? `${Object.keys(outputObj.rag_queries || {}).length} 条 query`
    : (outputObj.rag_query ? "1 条 agent query" : "—");

  // panel 2 — TopK 命中
  let p2 = "";
  let p2Summary = "—";
  if (n.node_id === "rag_retrieve") {
    // chunk 数据在 report.retrieval.chunks，节点 output 只给 top_scores
    const chunks = (ctx.report?.retrieval?.chunks || []).slice(0, 10);
    if (chunks.length) {
      p2 = chunks.map((c, i) => topkRow(i + 1, c)).join("");
      p2Summary = `top ${chunks.length} / 召回 ${outputObj.retrieved_chunk_count ?? chunks.length}`;
    } else if (Array.isArray(outputObj.top_scores) && outputObj.top_scores.length) {
      p2 = outputObj.top_scores.map((s, i) =>
        `<div class="topk-row"><div class="rk">#${i + 1}</div><div class="nm">score</div><div class="sc"></div><div class="sc"></div><div class="sc">${escapeHtml(String(s))}</div></div>`
      ).join("");
      p2Summary = `${outputObj.top_scores.length} 分数`;
    }
  } else if (/_agent$/.test(n.node_id || "")) {
    const ids = outputObj.retrieved_chunk_ids || [];
    const allChunks = ctx.report?.retrieval?.chunks || [];
    const byId = new Map(allChunks.map((c) => [c.id || c.chunk_id, c]));
    const matched = ids.map((id) => byId.get(id)).filter(Boolean);
    if (matched.length) {
      p2 = matched.map((c, i) => topkRow(i + 1, c)).join("");
      p2Summary = `${matched.length} chunk 引用`;
    } else if (ids.length) {
      p2 = ids.map((id, i) => `<div class="topk-row"><div class="rk">#${i + 1}</div><div class="nm">${escapeHtml(id)}</div><div class="sc"></div><div class="sc"></div><div class="sc">—</div></div>`).join("");
      p2Summary = `${ids.length} 引用 id`;
    }
  }

  // panel 3 — 输入 / 输出 schema
  const inSize = safeJsonSize(inputObj);
  const outSize = safeJsonSize(outputObj);
  const p3Summary = `input ${fmtBytes(inSize)} · output ${fmtBytes(outSize)}`;
  const p3 = `
    <div style="display:grid;grid-template-columns:1fr;gap:16px;">
      <div>
        <div style="font-size:12px;color:var(--ink-48);letter-spacing:-0.12px;margin-bottom:6px;">input</div>
        ${inSize ? `<pre>${escapeHtml(safeStringify(inputObj))}</pre>` : '<div class="pbody mute" style="padding:0;">折叠中 · 暂无数据</div>'}
      </div>
      <div>
        <div style="font-size:12px;color:var(--ink-48);letter-spacing:-0.12px;margin-bottom:6px;">output</div>
        ${outSize ? `<pre>${escapeHtml(safeStringify(outputObj))}</pre>` : '<div class="pbody mute" style="padding:0;">折叠中 · 暂无数据</div>'}
      </div>
    </div>`;

  // panel 4 — Agent 分支推理链
  let p4 = "";
  let p4Summary = "—";
  if (n.node_id === "chief_review" || n.node_id === "cross_check") {
    const branches = ctx.report?.agent_branches || ctx.report?.sub_agent_results || [];
    if (Array.isArray(branches) && branches.length) {
      p4 = branches.map((b) => agentBranchBlock(b)).join("");
      p4Summary = `${branches.length} 路并行`;
    }
  } else if (/_agent$/.test(n.node_id || "")) {
    p4 = agentBranchBlock(outputObj);
    p4Summary = `单 agent · ${(outputObj.reasoning_steps || []).length} 步`;
  } else if (n.node_id === "rag_retrieve") {
    const branches = ctx.report?.agent_branches || [];
    if (Array.isArray(branches) && branches.length) {
      const tags = branches.map((b) => escapeHtml(b.agent_type || b.task_id || b.task || "agent")).join(" · ");
      p4 = `<div class="pbody mute" style="padding:0;">下游 ${branches.length} 路 agent 将消费本节点的召回结果：${tags}</div>`;
      p4Summary = `${branches.length} 路下游`;
    }
  }

  return [
    panelFrame("查询构造", p1Summary, p1 || `<div class="pbody mute" style="padding:0;">折叠中 · 暂无数据</div>`),
    panelFrame("TopK · 命中 chunks", p2Summary, p2 || `<div class="pbody mute" style="padding:0;">折叠中 · 暂无数据</div>`),
    panelFrame("输入 / 输出 schema", p3Summary, p3),
    panelFrame("Agent 分支推理链", p4Summary, p4 || `<div class="pbody mute" style="padding:0;">折叠中 · 暂无数据</div>`),
  ].join("");
}

function panelFrame(title, indText, bodyHtml) {
  return `
    <details class="trc-panel">
      <summary>${escapeHtml(title)}<span class="ind">${escapeHtml(indText)}<span class="arrow"></span></span></summary>
      <div class="pbody">${bodyHtml}</div>
    </details>
  `;
}

function topkRow(rank, chunk) {
  const id = chunk.id || chunk.chunk_id || "";
  const title = chunk.rule_id || chunk.title || chunk.source_id || id;
  const snippet = (chunk.snippet || chunk.text || chunk.content || "").toString().slice(0, 120);
  const vec = chunk.vector_score ?? chunk.cos ?? chunk.cosine ?? chunk.score_vector;
  const rerank = chunk.score ?? chunk.rerank_score ?? chunk.final_score;
  const hit = chunk.hit ?? chunk.matched;
  return `
    <div class="topk-row">
      <div class="rk">#${rank}</div>
      <div class="nm">${escapeHtml(title)}<small>${escapeHtml(snippet)}${snippet.length >= 120 ? "…" : ""}</small></div>
      <div class="sc">${vec != null ? `cos ${Number(vec).toFixed(3)}` : "—"} <small>vec</small></div>
      <div class="sc">${rerank != null ? Number(rerank).toFixed(2) : "—"} <small>rerank</small></div>
      <div class="sc">${hit === false ? "—" : "命中"}</div>
    </div>
  `;
}

function agentBranchBlock(b) {
  if (!b || typeof b !== "object") return "";
  const name = b.task || b.agent_type || b.task_id || "Agent";
  const v = b.verdict || "—";
  const conf = b.confidence ?? "—";
  const llm = b.llm_used ? (b.llm_model || "yes") : "no";
  const steps = Array.isArray(b.reasoning_steps) ? b.reasoning_steps : [];
  const reasons = Array.isArray(b.reasons) ? b.reasons : [];
  const stepsHtml = steps.length
    ? `<pre>${escapeHtml(steps.map((s, i) => `${i + 1}. ${typeof s === "string" ? s : JSON.stringify(s)}`).join("\n"))}</pre>`
    : (reasons.length ? `<pre>${escapeHtml(reasons.join("\n"))}</pre>` : "");
  return `
    <div style="margin-bottom:14px;padding-bottom:14px;border-bottom:1px solid var(--divider-soft);">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
        <div style="font-weight:600;color:var(--ink);">${escapeHtml(name)}</div>
        <div style="font-size:12px;color:var(--ink-48);letter-spacing:-0.12px;">verdict ${escapeHtml(String(v))} · 置信 ${escapeHtml(String(conf))} · LLM ${escapeHtml(String(llm))}</div>
      </div>
      ${stepsHtml}
    </div>
  `;
}

function safeStringify(obj) {
  try {
    const s = JSON.stringify(obj, null, 2);
    if (s.length > 8000) return s.slice(0, 8000) + "\n... (截断，完整内容请用导出 trace JSON)";
    return s;
  } catch (e) {
    return String(e);
  }
}

// —— 导出 trace JSON —— //

function downloadTraceJson(report, caseId) {
  if (!report) return;
  try {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `trace-${caseId}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 0);
  } catch (err) {
    alert(`导出失败：${err.message || err}`);
  }
}

// —— mount —— //

export async function mount(outlet, params) {
  const caseId = (params && (params.id || params.caseId)) || "";

  // 防御性鉴权：shell.js 已闸门，但路由首次 mount 时序兜底
  const role = (window.shell && typeof window.shell.getRole === "function")
    ? window.shell.getRole()
    : (localStorage.getItem("rcr.role") || localStorage.getItem("role") || "client");
  if (role !== "admin") {
    navigate("#/cases");
    return;
  }

  if (window.shell) {
    window.shell.hideProgress();
    window.shell.setStepbar(`审查回放 · ${caseId}`, "", "");
    window.shell.setCrumb(`<b>管理端 · 审查回放</b> · ${escapeHtml(caseId)}`);
  }

  let tpl;
  try {
    tpl = await ensureAssets();
  } catch (err) {
    outlet.innerHTML = `<div class="trc-error">页面资源加载失败：${escapeHtml(err.message || String(err))}</div>`;
    return;
  }
  outlet.innerHTML = tpl;
  const root = outlet;

  if (!caseId) {
    showEmpty(root, "缺少 Case ID。请从 sidebar 或 Case 看板进入。");
    return;
  }

  // 拉数据
  let resp;
  try {
    resp = await api.cases.get(caseId);
  } catch (err) {
    const slot = root.querySelector('[data-trc="error-slot"]');
    if (slot) slot.innerHTML = `<div class="trc-error">Case 加载失败：${escapeHtml(err.message || String(err))}</div>`;
    showEmpty(root, "无法加载该 Case。请确认 Case ID 是否存在。");
    return;
  }

  const caseObj = (resp && resp.case) || {};
  const report = (resp && resp.latest_report) || null;
  const nodes = Array.isArray(report?.nodes) ? report.nodes : [];

  if (!report || nodes.length === 0) {
    // 标题/元信息也展示一下，便于排错
    const ctx0 = { caseObj, report, nodes: [], caseId, activeIdx: -1 };
    try { renderMeta(root, ctx0); } catch (_) {}
    showEmpty(root, report
      ? "latest_report 存在但 nodes 为空 — 该 Case 可能用旧版本生成，请重跑预审。"
      : "该 Case 尚未生成 latest_report — 请先在 Case 看板触发预审。");
    return;
  }

  // 默认激活第一个状态非 completed 的节点（更聚焦排错），否则第一个
  let activeIdx = nodes.findIndex((n) => {
    const s = String(n.status || "").toLowerCase();
    return s && s !== "completed" && s !== "pass" && s !== "ok";
  });
  if (activeIdx < 0) activeIdx = 0;

  const ctx = { caseObj, report, nodes, caseId, activeIdx };

  renderMeta(root, ctx);
  root.querySelector('[data-trc="layout"]').hidden = false;
  renderTimeline(root, ctx);
  renderDetail(root, ctx);

  // 事件 — 时间线点击切换
  const tl = root.querySelector('[data-trc="timeline"]');
  tl.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-idx]");
    if (!btn) return;
    const idx = Number(btn.dataset.idx);
    if (!Number.isFinite(idx) || idx === ctx.activeIdx) return;
    ctx.activeIdx = idx;
    // 重新渲染时间线与详情
    renderTimeline(root, ctx);
    renderDetail(root, ctx);
  });

  // 导出
  const exportBtn = root.querySelector('[data-trc="export"]');
  if (exportBtn) {
    exportBtn.addEventListener("click", () => downloadTraceJson(report, caseId));
  }
  // 返回客户视图
  for (const sel of ['[data-trc="back"]', '[data-trc="back-2"]']) {
    const btn = root.querySelector(sel);
    if (btn) btn.addEventListener("click", () => navigate(`#/cases/${encodeURIComponent(caseId)}`));
  }
}

function showEmpty(root, hint) {
  const layout = root.querySelector('[data-trc="layout"]');
  if (layout) layout.hidden = true;
  const empty = root.querySelector('[data-trc="empty"]');
  if (empty) {
    empty.hidden = false;
    const h = empty.querySelector('[data-trc="empty-h"]');
    if (h && hint) h.textContent = hint;
  }
}

export default { mount };
