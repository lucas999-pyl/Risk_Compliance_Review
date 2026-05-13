// precheck.js — Step 2 上传完成后展示资料预检结果。
// 当前后端 uploadDocuments 同步返回 package_precheck，无需轮询；
// 此模块封装"上传一批 → 拿到 precheck → 写回 ctx"的小流程，
// 并提供 fetchAfterRefresh：刷新进入 Step 3 时从 case_detail 重新拉一次。

import { api } from "/static/js/api.js";

export async function uploadAndPrecheck(caseId, files) {
  if (!Array.isArray(files) || files.length === 0) {
    throw new Error("没有要上传的文件");
  }
  const resp = await api.cases.uploadDocuments(caseId, files);
  return {
    documents: resp.documents || [],
    document_count: resp.document_count || 0,
    package_precheck: resp.package_precheck || null,
  };
}

// 进入 Step 3（刷新等）时拉取一次 case detail 拿最新 precheck。
export async function loadPrecheck(caseId) {
  const detail = await api.cases.get(caseId);
  return {
    documents: detail.documents || [],
    document_count: detail.document_count || (detail.documents || []).length,
    package_precheck: detail.package_precheck || null,
  };
}

// 计算 4 张 metric 卡的数字。
export function metricsFromPrecheck(precheck) {
  if (!precheck) return { recognized: 0, missing: 0, ready: 0, blocked: 0 };
  const docs = precheck.documents || [];
  const recognized = docs.filter((d) => d.detected_type && d.detected_type !== "unknown").length;
  const missing = (precheck.missing_documents || []).length;
  const ready = (precheck.available_checks || []).length;
  const blocked = (precheck.blocked_checks || []).length + (precheck.limited_checks || []).length;
  return { recognized, missing, ready, blocked };
}

// precheck.overall_status → "可继续" / "需补件" / "阻断"
export function statusLabel(precheck) {
  const s = (precheck && precheck.overall_status) || "ready";
  switch (s) {
    case "ready": return { tone: "pass", text: "已就绪，可进入下一步" };
    case "partial": return { tone: "warn", text: "部分受限，可继续但报告会标记" };
    case "needs_supplement": return { tone: "warn", text: "建议补件后再继续" };
    case "unreadable": return { tone: "block", text: "上传文件不可读，请重新上传" };
    default: return { tone: "mute", text: s };
  }
}
