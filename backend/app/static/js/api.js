// api.js — 后端 API 客户端封装。仅消费 factory.py 已有 endpoint，不新增。
// 错误兜底：response.ok 为 false 时抛 Error，message 含 status + 文本片段。

async function request(method, url, { body, headers, raw } = {}) {
  const init = { method, headers: { ...(headers || {}) } };
  if (body !== undefined) {
    if (body instanceof FormData) {
      init.body = body;
    } else {
      init.body = typeof body === "string" ? body : JSON.stringify(body);
      if (!init.headers["Content-Type"]) init.headers["Content-Type"] = "application/json";
    }
  }
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail = "";
    try {
      const text = await res.text();
      detail = text.slice(0, 240);
    } catch (_) {}
    throw new Error(`[${method} ${url}] ${res.status} ${res.statusText} ${detail}`);
  }
  if (raw) return res;
  const ct = res.headers.get("Content-Type") || "";
  if (ct.includes("application/json")) return res.json();
  return res.text();
}

const get = (url, opts) => request("GET", url, opts);
const post = (url, body, opts) => request("POST", url, { ...(opts || {}), body });
const del = (url, opts) => request("DELETE", url, opts);

export const api = {
  cases: {
    list: () => get("/chemical/cases"),
    create: (payload) => post("/chemical/cases", payload),
    get: (caseId) => get(`/chemical/cases/${encodeURIComponent(caseId)}`),
    delete: () => del("/chemical/cases"),
    deleteOne: (caseId) => del(`/chemical/cases/${encodeURIComponent(caseId)}`),
    uploadDocuments: (caseId, files) => {
      const fd = new FormData();
      for (const f of files) fd.append("documents", f);
      return post(`/chemical/cases/${encodeURIComponent(caseId)}/documents`, fd);
    },
    runReview: async (caseId, { reviewTask, topK } = {}) => {
      await api.knowledge.ensureLoaded();
      const fd = new FormData();
      if (reviewTask) fd.append("review_task", reviewTask);
      if (topK !== undefined) fd.append("top_k", String(topK));
      return post(`/chemical/cases/${encodeURIComponent(caseId)}/run-review`, fd);
    },
    retrievalPreview: (caseId, topK = 5) =>
      post("/chemical/retrieval-preview", { case_id: caseId, top_k: topK }),
    queryPresets: () => get("/chemical/query-presets"),
    uploadReview: (formData) => post("/chemical/upload-review", formData),
  },
  knowledge: {
    status: () => get("/chemical/knowledge/status"),
    chunks: () => get("/chemical/knowledge/chunks"),
    search: (query, targetMarkets = ["CN", "EU", "US"], topK = 5) =>
      post("/chemical/knowledge/search", { query, target_markets: targetMarkets, top_k: topK }),
    importDemoPack: () => post("/chemical/knowledge/import-demo-pack"),
    uploadPack: (manifestFile, sourceFiles) => {
      const fd = new FormData();
      fd.append("manifest_file", manifestFile);
      for (const f of sourceFiles) fd.append("source_files", f);
      return post("/chemical/knowledge/upload-pack", fd);
    },
    clear: () => del("/chemical/knowledge"),
    sourcePackZip: () => "/chemical/knowledge/source-pack.zip",
    // 自动检测 — 防止"知识库未加载"静默闸门（IMPLEMENTATION_LOG #1 现场补充）
    ensureLoaded: async () => {
      try {
        const st = await api.knowledge.status();
        const count = (st && (st.chunk_count ?? st.chunkCount)) || 0;
        if (count > 0) return st;
      } catch (_) { /* fall through to import */ }
      return api.knowledge.importDemoPack();
    },
  },
  technology: {
    runs: (payload) => post("/technology/runs", payload),
    evaluation: () => get("/technology/evaluation"),
  },
  evaluation: {
    chemical: () => get("/chemical/evaluation"),
  },
  vectorStore: () => get("/chemical/vector-store"),
  health: () => get("/health"),
};

export default api;
