// pages/admin-kb/index.js — 管理端·知识库工作台
// 路由：#/admin/kb（adminOnly，由 shell.js 闸门拦截 client 角色）
// 仅消费 api.knowledge.* 已封装方法，不新增后端 endpoint。

import { api } from "/static/js/api.js";

const HTML_URL = "/static/pages/admin-kb/admin-kb.html";
const CSS_URL = "/static/pages/admin-kb/admin-kb.css";
let cssLoaded = false;

function ensureCss() {
  if (cssLoaded) return;
  if (document.querySelector(`link[data-page="admin-kb"]`)) {
    cssLoaded = true;
    return;
  }
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = CSS_URL;
  link.dataset.page = "admin-kb";
  document.head.appendChild(link);
  cssLoaded = true;
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function fmtSize(bytes) {
  if (bytes == null || Number.isNaN(bytes)) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function fmtNumber(n) {
  if (n == null || Number.isNaN(n)) return "0";
  return Number(n).toLocaleString("en-US");
}

function fmtTs(v) {
  if (!v) return "—";
  try {
    const d = typeof v === "string" || typeof v === "number" ? new Date(v) : v;
    if (Number.isNaN(d.getTime())) return String(v);
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    return `${m}-${day} ${hh}:${mm}`;
  } catch (_) { return String(v); }
}

function pickRuleType(meta) {
  const t = (meta && (meta.type || meta.rule_type || meta.category || meta.source_type)) || "";
  return String(t || "规则");
}

function dotForType(t) {
  const s = String(t || "").toLowerCase();
  if (/(限制|受限|svhc|restrict|block)/.test(s)) return "block";
  if (/(限量|限值|warn|候选)/.test(s)) return "warn";
  return "pass";
}

// 把 chunk 列表聚合成"规则"行（按 rule_id / source 分组）
function groupChunksToRules(chunks) {
  const groups = new Map();
  for (const c of chunks || []) {
    const meta = c.metadata || c.meta || c || {};
    const rid = meta.rule_id || meta.ruleId || c.rule_id || meta.source_id || c.source_id
      || meta.source || c.source || meta.document || c.id || c.chunk_id || "—";
    const name = meta.rule_name_zh || meta.name || meta.title || meta.rule_name || meta.source_title
      || c.source_title || c.title || rid;
    const sub = meta.subtitle || meta.market || meta.jurisdiction || meta.source_subtitle || "";
    const type = pickRuleType(meta);
    const ts = meta.last_query_at || meta.last_queried_at || meta.updated_at || meta.timestamp || null;
    const key = String(rid);
    if (!groups.has(key)) {
      groups.set(key, { rid: key, name, sub, type, count: 0, ts });
    }
    const g = groups.get(key);
    g.count += 1;
    if (ts && (!g.ts || new Date(ts) > new Date(g.ts))) g.ts = ts;
  }
  return Array.from(groups.values()).sort((a, b) => b.count - a.count);
}

async function loadTemplate() {
  const res = await fetch(HTML_URL, { cache: "no-cache" });
  if (!res.ok) throw new Error(`加载模板失败 ${res.status}`);
  return res.text();
}

// —— 渲染：metric + rules + empty hint —— //

function paintStatus(outlet, st) {
  const q = (id) => outlet.querySelector(`#${id}`);
  const kb = (st && st.knowledge_base) || {};
  const vs = (st && st.vector_store) || {};
  const emb = (st && st.embedding) || {};
  const sourceCount = (st && (st.source_count ?? st.sourceCount ?? kb.source_count ?? kb.sourceCount)) ?? 0;
  const chunkCount = (st && (st.chunk_count ?? st.chunkCount ?? kb.chunk_count ?? kb.chunkCount)) ?? 0;
  const vectorCount = (st && (st.vector_count ?? st.vectorCount ?? vs.vector_count ?? vs.vectorCount)) ?? 0;
  const packId = (st && (st.pack_id ?? st.packId)) || "—";
  const provider = (st && (st.embedding_provider ?? st.embeddingProvider ?? emb.provider ?? vs.embedding_provider)) || "—";
  const model = (st && (st.embedding_model ?? st.embeddingModel ?? emb.model ?? vs.embedding_model)) || "—";

  const setNum = (id, n) => {
    const el = q(id);
    if (!el) return;
    el.textContent = fmtNumber(n);
    el.classList.toggle("empty", !n);
  };
  setNum("kb-mc-source", sourceCount);
  setNum("kb-mc-chunk", chunkCount);
  setNum("kb-mc-vector", vectorCount);

  q("kb-mc-source-pill").textContent = sourceCount ? `${fmtNumber(sourceCount)} 份` : "空";
  q("kb-mc-source-desc").textContent = packId !== "—" ? `pack: ${packId}` : "尚未导入规则源";
  q("kb-mc-chunk-pill").textContent = chunkCount ? "已切分" : "空";
  q("kb-mc-chunk-desc").textContent = chunkCount ? `平均块大小由后端切块器决定` : "尚未切分";
  q("kb-mc-vector-pill").textContent = vectorCount ? "同步" : "空";
  q("kb-mc-vector-desc").textContent = vectorCount === chunkCount && vectorCount
    ? "向量与 chunk 一致"
    : (vectorCount ? `已索引 ${fmtNumber(vectorCount)} 向量` : "尚未建索引");

  const modelEl = q("kb-mc-model");
  if (modelEl) modelEl.textContent = model;
  q("kb-mc-model-pill").textContent = provider !== "—" ? provider : "—";
  q("kb-mc-model-desc").textContent = provider !== "—" ? `provider · ${provider}` : "尚未配置";

  const hint = q("kb-empty-hint");
  if (hint) hint.hidden = chunkCount > 0;
}

function paintSources(outlet, sources) {
  const box = outlet.querySelector("#kb-sources");
  const cap = outlet.querySelector("#kb-sources-cap");
  if (!box) return;
  const items = Array.isArray(sources) ? sources : [];
  if (cap) cap.textContent = items.length ? `共 ${fmtNumber(items.length)} 份源文档` : "暂无知识源";
  if (!items.length) {
    box.innerHTML = `<div class="kb-rules-empty">暂无知识源。请上传官方源文档或导入演示包。</div>`;
    return;
  }
  box.innerHTML = items.map((s) => `
    <article class="kb-source-card">
      <div class="top"><strong>${escapeHtml(s.title || s.id || "未命名源")}</strong><span>${escapeHtml(s.jurisdiction || "GLOBAL")}</span></div>
      <div class="meta">${escapeHtml(s.source_type || "source")} · ${escapeHtml(s.version || "—")} · 生效 ${escapeHtml(s.effective_date || "—")} · chunks ${fmtNumber(s.chunk_count || 0)}</div>
      <div class="url">${escapeHtml(s.source_url || "")}</div>
    </article>
  `).join("");
}

function paintRules(outlet, chunks) {
  const body = outlet.querySelector("#kb-rules-body");
  const cap = outlet.querySelector("#kb-rules-cap");
  if (!body) return;
  const rules = groupChunksToRules(chunks || []);
  if (cap) cap.textContent = rules.length
    ? `共 ${fmtNumber(rules.length)} 条规则 · ${fmtNumber((chunks || []).length)} 个 chunk`
    : "暂无规则";
  if (!rules.length) {
    body.innerHTML = `<div class="kb-rules-empty">暂无已索引规则。请上传知识源文档或导入演示包。</div>`;
    return;
  }
  body.innerHTML = rules.slice(0, 200).map((r) => {
    const dot = dotForType(r.type);
    return `<div class="rw">
      <div class="rid">${escapeHtml(r.rid)}</div>
      <div class="nm">${escapeHtml(r.name)}${r.sub ? `<small>${escapeHtml(r.sub)}</small>` : ""}</div>
      <div><span class="chip-type"><span class="dot ${dot}"></span>${escapeHtml(r.type)}</span></div>
      <div class="ct">${fmtNumber(r.count)}</div>
      <div class="ts">${escapeHtml(fmtTs(r.ts))}</div>
    </div>`;
  }).join("");
}

async function refreshStatus(outlet) {
  try {
    const st = await api.knowledge.status();
    paintStatus(outlet, st);
    paintSources(outlet, (st && st.sources) || []);
    return st;
  } catch (err) {
    console.warn("[admin-kb] status failed", err);
    paintStatus(outlet, {});
    paintSources(outlet, []);
    return null;
  }
}

async function refreshChunks(outlet) {
  const body = outlet.querySelector("#kb-rules-body");
  if (body) body.innerHTML = `<div class="kb-rules-loading">加载 chunk 列表…</div>`;
  try {
    const resp = await api.knowledge.chunks();
    const chunks = Array.isArray(resp) ? resp : (resp && (resp.chunks || resp.items)) || [];
    paintRules(outlet, chunks);
  } catch (err) {
    console.warn("[admin-kb] chunks failed", err);
    if (body) body.innerHTML = `<div class="kb-rules-empty">加载失败：${escapeHtml(err.message || err)}</div>`;
  }
}

async function refreshAll(outlet) {
  await Promise.all([refreshStatus(outlet), refreshChunks(outlet)]);
}

// —— 检索 —— //

function bindSearch(outlet) {
  const input = outlet.querySelector("#kb-search-input");
  const btn = outlet.querySelector("#kb-search-btn");
  const out = outlet.querySelector("#kb-search-results");
  const marketBoxes = outlet.querySelectorAll(".kb-search-markets input[type=checkbox]");

  const doSearch = async () => {
    const query = (input.value || "").trim();
    if (!query) {
      out.innerHTML = `<div class="kb-search-msg">请输入 query。</div>`;
      return;
    }
    const markets = Array.from(marketBoxes).filter((b) => b.checked).map((b) => b.value);
    if (!markets.length) {
      out.innerHTML = `<div class="kb-search-msg err">至少勾选一个 target market。</div>`;
      return;
    }
    out.innerHTML = `<div class="kb-search-msg">检索中…</div>`;
    btn.disabled = true;
    try {
      const resp = await api.knowledge.search(query, markets, 5);
      const items = Array.isArray(resp)
        ? resp
        : (resp && (resp.results || resp.hits || resp.chunks || (resp.retrieval && resp.retrieval.chunks))) || [];
      if (!items.length) {
        out.innerHTML = `<div class="kb-search-msg">无结果。</div>`;
        return;
      }
      out.innerHTML = items.map((it, i) => {
        const meta = it.metadata || it.meta || {};
        const rid = meta.rule_id || it.rule_id || it.source_title || it.source_id || it.id || `#${i + 1}`;
        const score = it.score ?? it.rerank_score ?? it.vector_score ?? it.similarity ?? it.distance;
        const body = it.text || it.content || it.chunk || it.snippet || "";
        const scoreTxt = score != null && !Number.isNaN(Number(score))
          ? `score ${Number(score).toFixed(3)}` : "";
        return `<div class="kb-search-result">
          <div class="meta"><span class="rid">${escapeHtml(rid)}</span><span class="score">${escapeHtml(scoreTxt)}</span></div>
          <div class="body">${escapeHtml(String(body).slice(0, 600))}</div>
        </div>`;
      }).join("");
    } catch (err) {
      out.innerHTML = `<div class="kb-search-msg err">检索失败：${escapeHtml(err.message || err)}</div>`;
    } finally {
      btn.disabled = false;
    }
  };

  btn.addEventListener("click", doSearch);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); doSearch(); }
  });
}

// —— 上传 modal —— //

function bindUploadModal(outlet) {
  const modal = outlet.querySelector("#kb-upload-modal");
  const openBtn = outlet.querySelector("#kb-upload-btn");
  const closeBtn = outlet.querySelector("#kb-upload-close");
  const cancelBtn = outlet.querySelector("#kb-upload-cancel");
  const submitBtn = outlet.querySelector("#kb-upload-submit");
  const manifestInput = outlet.querySelector("#kb-manifest-input");
  const sourceInput = outlet.querySelector("#kb-source-input");
  const manifestBox = outlet.querySelector("#kb-manifest-file");
  const sourceList = outlet.querySelector("#kb-source-list");
  const msg = outlet.querySelector("#kb-upload-msg");

  const reset = () => {
    manifestInput.value = "";
    sourceInput.value = "";
    manifestBox.innerHTML = "";
    sourceList.innerHTML = "";
    msg.textContent = "";
    msg.className = "kb-modal-msg";
    submitBtn.disabled = false;
  };
  const open = () => { reset(); modal.hidden = false; };
  const close = () => { modal.hidden = true; };
  openBtn.addEventListener("click", open);
  closeBtn.addEventListener("click", close);
  cancelBtn.addEventListener("click", close);
  modal.addEventListener("click", (e) => { if (e.target === modal) close(); });

  manifestInput.addEventListener("change", () => {
    const f = manifestInput.files && manifestInput.files[0];
    manifestBox.innerHTML = f ? `<div><span class="nm">${escapeHtml(f.name)}</span><span class="sz">${escapeHtml(fmtSize(f.size))}</span></div>` : "";
  });
  sourceInput.addEventListener("change", () => {
    const files = Array.from(sourceInput.files || []);
    sourceList.innerHTML = files.map((f) =>
      `<div><span class="nm">${escapeHtml(f.name)}</span><span class="sz">${escapeHtml(fmtSize(f.size))}</span></div>`
    ).join("");
  });

  submitBtn.addEventListener("click", async () => {
    const mf = manifestInput.files && manifestInput.files[0];
    const sf = Array.from(sourceInput.files || []);
    if (!mf) { msg.textContent = "请选择 Manifest JSON 文件"; msg.className = "kb-modal-msg err"; return; }
    if (!sf.length) { msg.textContent = "请至少选择一份规则源文档"; msg.className = "kb-modal-msg err"; return; }
    submitBtn.disabled = true;
    msg.textContent = "上传中…"; msg.className = "kb-modal-msg";
    try {
      await api.knowledge.uploadPack(mf, sf);
      msg.textContent = "上传成功，正在刷新…"; msg.className = "kb-modal-msg ok";
      await refreshAll(outlet);
      setTimeout(() => { close(); }, 800);
    } catch (err) {
      msg.textContent = `上传失败：${err.message || err}`;
      msg.className = "kb-modal-msg err";
      submitBtn.disabled = false;
    }
  });
}

// —— 清空（双确认）—— //

function bindClearModal(outlet) {
  const modal = outlet.querySelector("#kb-clear-modal");
  const openBtn = outlet.querySelector("#kb-clear-btn");
  const closeBtn = outlet.querySelector("#kb-clear-close");
  const cancelBtn = outlet.querySelector("#kb-clear-cancel");
  const confirmBtn = outlet.querySelector("#kb-clear-confirm-btn");
  const input = outlet.querySelector("#kb-clear-confirm-input");
  const msg = outlet.querySelector("#kb-clear-msg");

  const close = () => { modal.hidden = true; };
  const open = () => {
    // 第一道：浏览器原生 confirm
    if (!window.confirm("确定要清空整个知识库吗？此操作不可撤销。")) return;
    input.value = "";
    msg.textContent = ""; msg.className = "kb-modal-msg";
    confirmBtn.disabled = true;
    modal.hidden = false;
    setTimeout(() => input.focus(), 50);
  };
  openBtn.addEventListener("click", open);
  closeBtn.addEventListener("click", close);
  cancelBtn.addEventListener("click", close);
  modal.addEventListener("click", (e) => { if (e.target === modal) close(); });

  input.addEventListener("input", () => {
    confirmBtn.disabled = input.value.trim() !== "CLEAR";
  });

  confirmBtn.addEventListener("click", async () => {
    if (input.value.trim() !== "CLEAR") return;
    confirmBtn.disabled = true;
    msg.textContent = "清空中…"; msg.className = "kb-modal-msg";
    try {
      await api.knowledge.clear();
      msg.textContent = "已清空"; msg.className = "kb-modal-msg ok";
      await refreshAll(outlet);
      setTimeout(() => { close(); }, 600);
    } catch (err) {
      msg.textContent = `清空失败：${err.message || err}`;
      msg.className = "kb-modal-msg err";
      confirmBtn.disabled = false;
    }
  });
}

function bindImportDemo(outlet) {
  const btn = outlet.querySelector("#kb-import-demo-btn");
  const hintLink = outlet.querySelector("#kb-hint-import-link");
  const run = async (trigger) => {
    if (!window.confirm("导入演示包将覆盖当前 chunk 与向量索引，确定继续？")) return;
    const original = trigger.textContent;
    trigger.textContent = "导入中…";
    trigger.setAttribute("disabled", "");
    try {
      await api.knowledge.importDemoPack();
      await refreshAll(outlet);
    } catch (err) {
      alert(`导入失败：${err.message || err}`);
    } finally {
      trigger.textContent = original;
      trigger.removeAttribute("disabled");
    }
  };
  btn.addEventListener("click", () => run(btn));
  if (hintLink) {
    hintLink.addEventListener("click", (e) => { e.preventDefault(); run(btn); });
  }
}

function bindDownloadPack(outlet) {
  const btn = outlet.querySelector("#kb-download-pack-btn");
  btn.addEventListener("click", () => {
    try {
      const url = api.knowledge.sourcePackZip();
      window.open(url, "_blank");
    } catch (err) {
      alert(`下载失败：${err.message || err}`);
    }
  });
}

// —— mount —— //

export async function mount(outlet, _params) {
  ensureCss();
  outlet.innerHTML = `<div style="padding:64px 80px;color:var(--ink-48);">加载知识库工作台…</div>`;
  try {
    const html = await loadTemplate();
    outlet.innerHTML = html;
  } catch (err) {
    outlet.innerHTML = `<div style="padding:64px 80px;color:var(--block);">模板加载失败：${escapeHtml(err.message || err)}</div>`;
    return;
  }

  // shell 全局态：admin-kb 不需要 wizard 进度条
  try {
    if (window.shell) {
      window.shell.hideProgress && window.shell.hideProgress();
      window.shell.setStepbar && window.shell.setStepbar("知识库管理", "", "");
      window.shell.setCrumb && window.shell.setCrumb("·&nbsp;&nbsp;<b>管理端 · 知识库工作台</b>");
    }
  } catch (_) { /* 非阻塞 */ }

  bindSearch(outlet);
  bindUploadModal(outlet);
  bindClearModal(outlet);
  bindImportDemo(outlet);
  bindDownloadPack(outlet);

  await refreshAll(outlet);
}

export default { mount };
