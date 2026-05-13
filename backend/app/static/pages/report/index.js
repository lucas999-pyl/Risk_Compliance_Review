// pages/report/index.js — 报告页 3 态（默认 / 抽屉 / 待重跑），含未生成 / 加载 / 错误兜底。
// 入口：export async function mount(outlet, params)
//   params.id : Case ID（来自路由 #/cases/:id）
//
// 数据契约（只读，Phase 1 已落地）：
//   GET /chemical/cases/:id → { case, documents, document_count, latest_report, package_precheck }
//   case.range_dirty (boolean, 可选)  · 若不存在按 false 处理
//   latest_report.customer_report.issue_groups[].items[] 提供客户视角不合规清单
//   latest_report.findings[] 是规则引擎 compat 输出（fallback）
//
// 不引框架、原生 ES Module；不写后端、不改其他文件域。

import { api } from "/static/js/api.js";

const HTML_URL = new URL("./report.html", import.meta.url).pathname;
const CSS_URL = new URL("./report.css", import.meta.url).pathname;
const CSS_ID = "rcr-report-css";

let htmlTemplatePromise = null;
function loadTemplate() {
  if (!htmlTemplatePromise) {
    htmlTemplatePromise = fetch(HTML_URL, { cache: "no-cache" }).then((r) => {
      if (!r.ok) throw new Error(`load report.html ${r.status}`);
      return r.text();
    });
  }
  return htmlTemplatePromise;
}

function ensureCss() {
  if (document.getElementById(CSS_ID)) return;
  const link = document.createElement("link");
  link.id = CSS_ID;
  link.rel = "stylesheet";
  link.href = CSS_URL;
  document.head.appendChild(link);
}

function getRole() {
  if (window.shell && typeof window.shell.getRole === "function") return window.shell.getRole();
  return localStorage.getItem("rcr.role") || "client";
}

function setShellChrome(caseObj) {
  // 报告页隐藏顶部 wizard 进度条；stepbar 显示 case 标题。
  if (window.shell) {
    if (typeof window.shell.hideProgress === "function") window.shell.hideProgress();
    if (typeof window.shell.setStepbar === "function") {
      const title = (caseObj && (caseObj.title || caseObj.id)) || "报告";
      window.shell.setStepbar(`报告 · ${title}`, "", "");
    }
    if (typeof window.shell.setCrumb === "function") {
      const idShort = caseObj && caseObj.id ? caseObj.id : "";
      window.shell.setCrumb(`·&nbsp;&nbsp;<b>报告 · ${escapeHtml(idShort)}</b>`);
    }
  }
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));
}

// —— verdict → dot/label/tag —— //
function verdictMeta(verdict) {
  // 客户报告 customer_report.verdict ∈ pass / needs_review / not_approved / needs_supplement
  // 规则引擎 latest_report.verdict ∈ 合规 / 复核 / 不合规
  const map = {
    // 合规预审通过 —— 不写"可进入下一步"，因为"下一步"对客户语义模糊
    pass: { dot: "pass", label: "合规预审通过", tag: "审查结论 · 已生成报告" },
    needs_review: { dot: "warn", label: "需复核", tag: "审查结论" },
    not_approved: { dot: "block", label: "不建议准入", tag: "审查结论 · 不通过" },
    needs_supplement: { dot: "warn", label: "待补件", tag: "审查结论" },
    合规: { dot: "pass", label: "合规预审通过", tag: "审查结论 · 已生成报告" },
    复核: { dot: "warn", label: "需复核", tag: "审查结论" },
    不合规: { dot: "block", label: "不建议准入", tag: "审查结论 · 不通过" },
  };
  return map[verdict] || { dot: "mute", label: verdict || "—", tag: "审查结论" };
}

function severityMeta(severity) {
  // severity in (block / warn / pass / mute / high / medium / low / info)
  const s = String(severity || "").toLowerCase();
  if (s === "block" || s === "high" || s === "not_approved") {
    return { dot: "block", text: "严重 · 阻断" };
  }
  if (s === "warn" || s === "medium" || s === "needs_review" || s === "needs_supplement") {
    return { dot: "warn", text: "需复核" };
  }
  if (s === "pass" || s === "low" || s === "info") {
    return { dot: "pass", text: "可审" };
  }
  return { dot: "mute", text: "—" };
}

const RULE_NAME_ZH = {
  document_completeness_precheck: "资料完整性预检",
  formula_components_missing: "配方组分缺失核查",
  package_precheck: "资料包预检",
  knowledge_pack_missing_review: "规则库资料缺失复核",
  knowledge_no_match_review: "法规知识未命中复核",
  sds_missing_sections: "安全技术说明书关键章节缺失核查",
  sds_key_sections: "安全技术说明书关键章节核查",
  tsca_inventory_match: "美国化学品清单状态核查",
  hazardous_catalog_match: "危险化学品目录命中核查",
  ghs_label_pictogram_missing: "化学品分类标签与象形图核查",
  sds_section_completeness: "安全技术说明书章节完整性核查",
  incompatibility_oxidizer_flammable: "可燃液体与氧化剂禁忌组合",
  incompatibility_hypochlorite_acid: "次氯酸盐与酸类禁忌组合",
  source_backed_no_restricted_demo_match: "禁限用物质证据化筛查",
  svhc_threshold_match: "欧盟高度关注物质阈值核查",
  voc_limit_exceeded: "挥发性有机物限值合规核查",
  formula_cas_missing: "配方组分登记号完整性核查",
  process_parameters_missing: "工艺关键参数完整性核查",
  flammable_storage_missing: "可燃液体储存条件核查",
  enterprise_redline_benzene: "企业红线禁苯核查",
  transport_un_mismatch: "运输编号与危险类别一致性核查",
  sds_revision_outdated: "安全技术说明书修订日期时效核查",
  oxidizer_high_temperature_process: "氧化剂高温工艺安全核查",
  unknown_substance_review: "未知 / 未命中物质复核",
  manual_review: "人工复核",
};

function ruleNameZh(ruleId) {
  const value = String(ruleId || "");
  return RULE_NAME_ZH[value] || value || "—";
}

function marketLabel(market) {
  return {
    CN: "中国",
    EU: "欧盟",
    US: "美国",
    KR: "韩国",
    JP: "日本",
  }[market] || market || "";
}

function localizeRuleText(text) {
  let out = String(text || "");
  Object.entries(RULE_NAME_ZH).forEach(([id, zh]) => {
    out = out.replaceAll(`规则 ${id}`, `规则 ${zh}`);
    out = out.replaceAll(`命中规则 ${id}`, `命中${zh}`);
    out = out.replaceAll(id, zh);
  });
  const labelMap = [
    [/\bREACH\/SVHC\b/g, "欧盟化学品法规/高度关注物质"],
    [/\bTSCA\/HCS\b/g, "美国化学品清单/危害沟通标准"],
    [/\bTSCA\b/g, "美国化学品清单"],
    [/\bGHS\b/g, "全球统一分类和标签制度"],
    [/\bSDS\b/g, "安全技术说明书"],
    [/\bMSDS\b/g, "安全技术说明书"],
    [/\bVOC\b/g, "挥发性有机物"],
    [/\bCAS\b/g, "化学文摘登记号"],
    [/\bSVHC\b/g, "高度关注物质"],
    [/\bREACH\b/g, "欧盟化学品法规"],
    [/\bHCS\b/g, "危害沟通标准"],
    [/\bEHS\b/g, "环境健康安全"],
    [/\bUN\s*编号\b/g, "运输编号"],
    [/\bUN\b/g, "运输编号"],
  ];
  labelMap.forEach(([pattern, zh]) => { out = out.replace(pattern, zh); });
  return out;
}

function businessRuleText(ruleId, fallback) {
  const map = {
    document_completeness_precheck: "准入要求：资料包必须达到可审查状态，文件可读、类型明确且覆盖所选审查范围。执行要求：文件不可读、类型不清或关键资料缺失时，先补齐资料，不进入正式准入判断。",
    package_precheck: "准入要求：资料包应先完成可读性、资料类型和关键证据覆盖检查。执行要求：未覆盖所选审查范围时，退回补件后重新预检。",
    sds_missing_sections: "准入要求：安全技术说明书应包含法规要求的关键章节，且章节内容可用于危害、储运和应急判断。执行要求：关键章节缺失或内容为空时，不作为完整准入依据，要求供应商补充有效版本。",
    formula_components_missing: "准入要求：配方资料应提供组分名称、登记号及浓度或浓度范围，保密成分也需提供可审查的合规声明。执行要求：成分身份或浓度缺失时，不进入自动放行，要求供应商补齐可核验资料。",
    process_parameters_missing: "准入要求：工艺资料应明确温度、压力、转速、关键步骤及必要安全控制条件。执行要求：关键工艺参数缺失时，先补充工艺说明或由工艺安全负责人确认。",
    incompatibility_oxidizer_flammable: "准入要求：可燃液体不得与氧化剂在同一配方、同一工艺步骤或同一不兼容储存单元中混配、共用或共存。执行要求：命中该组合时暂停当前方案，要求供应商拆分工艺、调整配方或提供经批准的隔离控制方案。",
    incompatibility_hypochlorite_acid: "准入要求：次氯酸盐不得与盐酸等酸类同槽、同釜或同步骤接触。执行要求：存在释放氯气或放热失控风险时，直接阻断当前方案，供应商需调整配方/工艺后重新提交。",
    hazardous_catalog_match: "准入要求：命中危险化学品目录的物质，需确认经营许可、储存条件、运输资质和企业适用边界。执行要求：许可或控制条件未确认前，不进入采购准入放行。",
    tsca_inventory_match: "准入要求：面向美国市场时，应确认物质清单状态、用途边界和标签/安全技术说明书义务。执行要求：清单状态或用途边界未确认前，转法规负责人复核。",
    svhc_threshold_match: "准入要求：含欧盟高度关注物质或处于阈值边界时，应具备供应商证明、客户披露义务判断和用途边界说明。执行要求：证明或披露判断缺失时，不建议直接准入。",
    ghs_label_pictogram_missing: "准入要求：危险品标签应包含产品标识、信号词、象形图、危害/防范说明和供应商信息。执行要求：任一关键标签要素缺失时，要求供应商修订标签后再审。",
    flammable_storage_missing: "准入要求：含可燃液体时，储运资料需明确防火隔离、通风、防爆电气和储存温度等控制条件。执行要求：控制条件缺失时，不进入仓储或现场试用。",
    oxidizer_high_temperature_process: "准入要求：氧化剂涉及加热、高温或热源工艺时，应提供稳定性、冷却联锁、泄压和工艺安全确认。执行要求：工艺安全确认缺失时，转工艺安全负责人复核。",
    transport_un_mismatch: "准入要求：运输编号应与物料危险类别和安全技术说明书第 2/14 章一致。执行要求：运输分类明显不一致时，要求供应商重新出具运输分类依据。",
    enterprise_redline_benzene: "准入要求：命中企业红线物质时，当前物料或配方不得进入新供应商准入流程。执行要求：除非完成企业例外审批，否则直接阻断。",
    voc_limit_exceeded: "准入要求：挥发性有机物检测值不得超过目标市场或企业限值。执行要求：超限时当前配方不得按该用途准入，需调整配方并重新检测。",
    sds_revision_outdated: "准入要求：安全技术说明书版本应有效、日期可追溯，并能代表当前配方。执行要求：版本过旧或不可追溯时，要求供应商提供有效版本后再审查。",
    unknown_substance_review: "准入要求：组分身份应可核验并纳入企业物质主数据或可审查的替代证明。执行要求：未知物质或身份无法确认时，不自动放行。",
  };
  if (map[ruleId]) return map[ruleId];
  const text = localizeRuleText(fallback || "");
  if (text.includes("执行要求：")) return text;
  return text ? `准入要求：${text} 执行要求：证据不足或边界不清时，转法规负责人复核后再决定是否准入。` : "";
}

function splitQuote(text) {
  const localized = localizeRuleText(text);
  const markers = [
    "执行要求：",
    "补充说明：",
  ];
  const indexes = markers.map((m) => localized.indexOf(m)).filter((i) => i >= 0);
  if (!indexes.length) return { main: localized, supplement: "" };
  const idx = Math.min(...indexes);
  return {
    main: localized.slice(0, idx).trim(),
    supplement: localized.slice(idx).trim(),
  };
}

function quoteBlockHtml(text) {
  const parts = splitQuote(text);
  return `<blockquote>${parts.main ? `<span class="quote-main">${escapeHtml(parts.main)}</span>` : ""}${parts.supplement ? `<span class="quote-supplement">${escapeHtml(parts.supplement)}</span>` : ""}</blockquote>`;
}

// —— 提取 findings：优先 customer_report.issue_groups → fallback latest_report.findings —— //
function extractFindings(latestReport) {
  if (!latestReport) return [];
  const cr = latestReport.customer_report;
  if (cr && Array.isArray(cr.issue_groups) && cr.issue_groups.length) {
    const out = [];
    for (const group of cr.issue_groups) {
      for (const item of group.items || []) {
        const ruleId = item.rule_id || (item.rule && item.rule.id) || "—";
        const rawRuleName = item.rule_name_zh || (item.rule && item.rule.name_zh) || ruleId;
        out.push({
          no: item.id || item.issue_id || `I-${String(out.length + 1).padStart(3, "0")}`,
          rule_id: ruleId,
          // 中文名优先用于主标题（sub-Y 透传），fallback 到英文 rule_id
          rule_name_zh: localizeRuleText(ruleNameZh(rawRuleName)),
          violated_rule_id: item.violated_rule_id || ruleId,
          // 法规出处副标题（如 "GB 15603-2022 第 6.4.2 条"）
          regulation_ref: item.regulation_ref || (item.rule && item.rule.regulation_ref) || "",
          // 法规原文摘录
          regulation_excerpt: item.regulation_excerpt || (item.rule && item.rule.regulation_excerpt) || "",
          rule_text: item.rule_text || (item.rule && item.rule.text) || "",
          user_quote: item.user_text || (item.source && item.source.text) || "",
          suggestion: item.recommendation || "",
          severity: item.severity || severityFromStatus(item.status),
          evidence_ref: (item.source && item.source.evidence_refs) || [],
        });
      }
    }
    return out;
  }
  // fallback：legacy findings 数组
  const fs = Array.isArray(latestReport.findings) ? latestReport.findings : [];
  return fs
    .filter((f) => (f.severity || "").toLowerCase() !== "info" && f.issue_type !== "chemical_verdict")
    .map((f, i) => ({
      no: `F-${String(i + 1).padStart(2, "0")}`,
      rule_id: (f.regulation_refs && f.regulation_refs[0]) || f.issue_type || "—",
      rule_name_zh: localizeRuleText(ruleNameZh(f.rule_name_zh || f.issue_type)),
      violated_rule_id: f.violated_rule_id || f.issue_type || "",
      regulation_ref: f.regulation_ref || (f.regulation_refs && f.regulation_refs[0]) || "",
      regulation_excerpt: f.regulation_excerpt || "",
      rule_text: f.conclusion || "",
      user_quote: (f.evidence_ids || []).join(" / "),
      suggestion: f.conclusion || "",
      severity: f.severity || "warn",
      evidence_ref: f.evidence_ids || [],
    }));
}

function severityFromStatus(status) {
  if (status === "not_approved") return "block";
  if (status === "needs_supplement" || status === "needs_review") return "warn";
  return "warn";
}

// —— 时间线 nodes 派生 —— //
function buildTimeline(detail) {
  const caseObj = detail.case || {};
  const status = caseObj.status || "";
  const verdict = caseObj.latest_verdict || (detail.latest_report && detail.latest_report.verdict);
  const docCount = detail.document_count || 0;
  const generatedAt = detail.latest_report && (detail.latest_report.generated_at || (detail.latest_report.report_metadata && detail.latest_report.report_metadata.generated_at));
  const created = caseObj.created_at || "";

  const fmt = (iso) => {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      const mm = String(d.getMonth() + 1).padStart(2, "0");
      const dd = String(d.getDate()).padStart(2, "0");
      const hh = String(d.getHours()).padStart(2, "0");
      const mi = String(d.getMinutes()).padStart(2, "0");
      return `${mm}-${dd} ${hh}:${mi}`;
    } catch (_) { return iso; }
  };

  const hasReport = !!detail.latest_report;
  return [
    { dot: "pass", name: "Step 1 · 案件基本信息", sub: caseObj.title || caseObj.id || "", ts: fmt(created) },
    { dot: docCount > 0 ? "pass" : "mute", name: "Step 2 · 上传资料包", sub: docCount > 0 ? `${docCount} 份文件` : "未上传", ts: docCount > 0 ? fmt(created) : "未发生" },
    { dot: detail.package_precheck ? "pass" : "mute", name: "Step 3 · 资料预检", sub: detail.package_precheck ? "已完成" : "未完成", ts: detail.package_precheck ? fmt(created) : "未发生" },
    { dot: caseObj.check_types && caseObj.check_types.length ? "pass" : "mute", name: "Step 4 · 审查范围", sub: caseObj.check_types ? `已选 ${caseObj.check_types.length} 项` : "未确认", ts: "—" },
    { dot: hasReport ? (verdict === "pass" || verdict === "合规" ? "pass" : "warn") : "mute", name: "Step 5 · 运行预审", sub: hasReport ? `结论 · ${verdictMeta(verdict).label}` : "未运行", ts: fmt(generatedAt) },
    { dot: hasReport && status === "ready_for_next_step" ? "pass" : "mute", name: "报告签发 / 归档", sub: hasReport ? "可下载 PDF" : "等待签发", ts: hasReport ? fmt(generatedAt) : "未发生" },
  ];
}

// —— 渲染 —— //
function renderFindings(root, findings, opts) {
  const slot = root.querySelector('[data-slot="findings"]');
  const head = root.querySelector('[data-slot="findings-h"]');
  const empty = root.querySelector('[data-slot="findings-empty"]');
  if (!findings.length) {
    slot.innerHTML = "";
    head.textContent = "不合规事项 · 0 项";
    empty.hidden = false;
    return;
  }
  empty.hidden = true;
  head.textContent = `不合规事项 · ${findings.length} 项`;
  slot.innerHTML = findings.map((f, idx) => {
    const tile = idx % 2 === 0 ? "tile-white" : "tile-parchment";
    const sev = severityMeta(f.severity);
    const num = String(idx + 1).padStart(2, "0");
    // 主标题：优先中文规则名，fallback 到英文 id
    const title = localizeRuleText(f.rule_name_zh || ruleNameZh(f.violated_rule_id || f.rule_id) || "—");
    // 副标题：法规出处 GB 编号 / 条文
    const subRef = f.regulation_ref || "";
    // 客户报告优先展示业务化准入要求，避免暴露规则库内部原文。
    const regExcerpt = f.regulation_excerpt || "";
    const ruleQuote = businessRuleText(f.rule_id || f.violated_rule_id, f.rule_text || regExcerpt);
    return `
      <div class="finding ${tile}" data-finding-no="${escapeHtml(f.no)}">
        <div class="num">${num}</div>
        <div class="body">
          <div class="row">
            <div class="k">违反规则</div>
            <div class="v">
              <div class="rule-id">${escapeHtml(title)}</div>
              ${subRef ? `<div class="rule-sub" style="font-size:12px;color:var(--ink-48);margin-top:2px;letter-spacing:-0.1px;">${escapeHtml(subRef)}</div>` : ""}
              ${ruleQuote ? quoteBlockHtml(ruleQuote) : ""}
            </div>
          </div>
          ${f.user_quote ? `<div class="row"><div class="k">用户原文</div><div class="v">${quoteBlockHtml(f.user_quote)}</div></div>` : ""}
          ${f.suggestion ? `<div class="row"><div class="k">改进建议</div><div class="v">${escapeHtml(f.suggestion)}</div></div>` : ""}
        </div>
        <div class="sev">
          <span class="chip-sev"><span class="dot ${sev.dot}"></span>${escapeHtml(sev.text)}</span>
          <button class="evi admin-only" data-action="view-evidence" data-finding-no="${escapeHtml(f.no)}">查看证据 →</button>
        </div>
      </div>`;
  }).join("");
}

function renderStatusChips(root, detail, rerun) {
  const slot = root.querySelector('[data-slot="status-chips"]');
  if (!slot) return;
  const lr = detail.latest_report || {};
  const cr = lr.customer_report || {};
  const exec = cr.executive_summary || {};
  const verdict = cr.verdict || lr.verdict;
  const vm = verdictMeta(verdict);

  const chips = [];
  if (typeof exec.issue_count === "number") {
    chips.push(`<span class="chip"><span class="dot warn"></span>问题 ${exec.issue_count}</span>`);
  }
  if (typeof exec.supplement_count === "number") {
    chips.push(`<span class="chip"><span class="dot mute"></span>需补 ${exec.supplement_count}</span>`);
  }
  if (typeof exec.needs_review_count === "number") {
    chips.push(`<span class="chip"><span class="dot warn"></span>需复核 ${exec.needs_review_count}</span>`);
  }
  if (typeof exec.not_approved_count === "number") {
    chips.push(`<span class="chip"><span class="dot block"></span>阻断 ${exec.not_approved_count}</span>`);
  }
  chips.push(`<span class="conclude"><span class="dot ${vm.dot}"></span>结论 · ${escapeHtml(vm.label)}</span>`);
  if (rerun) {
    chips.push(`<span class="conclude rerun-chip" style="margin-left:6px;"><span class="dot warn"></span>数据已变更 · 待重跑</span>`);
  }
  slot.innerHTML = chips.join("");
}

function renderHero(root, detail, rerun) {
  const lr = detail.latest_report || {};
  const cr = lr.customer_report || {};
  const verdict = cr.verdict || lr.verdict;
  const vm = verdictMeta(verdict);
  const lead = localizeRuleText(cr.summary || (lr.reasons && lr.reasons[0]) || "");

  const hero = root.querySelector('[data-slot="hero"]');
  hero.classList.toggle("mute", !!rerun);

  const dot = root.querySelector('[data-slot="hero-dot"]');
  dot.className = "dot lg " + (rerun ? "mute" : vm.dot);

  root.querySelector('[data-slot="hero-tag"]').textContent = rerun ? "上一次结论（已失效）" : vm.tag;
  // pass 态强制使用前端文案（"合规预审通过"），覆盖后端的 "可进入下一步" —— 后者对客户语义模糊
  const isPass = verdict === "pass" || verdict === "合规";
  root.querySelector('[data-slot="hero-verdict"]').textContent = rerun
    ? vm.label
    : (isPass ? vm.label : (cr.verdict_label || vm.label));
  root.querySelector('[data-slot="hero-lead"]').textContent = rerun
    ? "由于审查范围已被调整，原结论与下方清单不再代表当前 Case 状态。请点击右上「重新运行预审」生成新报告。"
    : lead;

  const foot = root.querySelector('[data-slot="hero-foot"]');
  const generated = lr.generated_at || (lr.report_metadata && lr.report_metadata.generated_at) || "";
  const kbVer = (lr.knowledge_pack && (lr.knowledge_pack.version || lr.knowledge_pack.pack_id)) || "";
  const reviewer = lr.agent_orchestration && lr.agent_orchestration.llm_model
    ? `主审 AI · ${lr.agent_orchestration.llm_model}`
    : "主审 AI 复核";
  const parts = [];
  if (generated) parts.push(`<span>审查日期 ${escapeHtml(String(generated).slice(0, 10))}</span>`);
  if (kbVer) parts.push(`<span>规则库 ${escapeHtml(kbVer)}</span>`);
  parts.push(`<span>${escapeHtml(reviewer)}</span>`);
  foot.innerHTML = parts.join("");
}

function renderStatusBar(root, detail) {
  const caseObj = detail.case || {};
  root.querySelector('[data-slot="case-cap"]').textContent =
    `${caseObj.id || "—"} · ${caseObj.intended_use || "市场准入预审"} · ${(caseObj.target_markets || []).map(marketLabel).join("/")}`;
  root.querySelector('[data-slot="case-title"]').textContent = caseObj.title || "(未命名 Case)";
  const generated = detail.latest_report && (detail.latest_report.generated_at || (detail.latest_report.report_metadata && detail.latest_report.report_metadata.generated_at));
  root.querySelector('[data-slot="footer-right"]').textContent =
    `${caseObj.id || ""} ${generated ? "· " + String(generated).slice(0, 10) : ""}`;
}

function renderDrawerTimeline(root, detail) {
  const nodes = buildTimeline(detail);
  const panel = root.querySelector('[data-slot="drawer-panel"]');
  if (panel.dataset.tabActive !== "timeline") return;
  panel.innerHTML = nodes.map((n, i) => `
    <div class="tl-node ${i === 4 ? "curr" : ""}" data-step="${i}">
      <div class="stem"><span class="dot ${n.dot}"></span></div>
      <div class="nm">${escapeHtml(n.name)}<small>${escapeHtml(n.sub)}</small></div>
      <div class="ts">${escapeHtml(n.ts)}</div>
    </div>`).join("");
}

function renderDrawerPanel(root, detail, tab) {
  const panel = root.querySelector('[data-slot="drawer-panel"]');
  panel.dataset.tabActive = tab;
  if (tab === "timeline") {
    renderDrawerTimeline(root, detail);
    return;
  }
  // admin tabs
  const lr = detail.latest_report || {};
  if (tab === "rag-evidence") {
    const chunks = (lr.retrieval && lr.retrieval.chunks) || [];
    if (!chunks.length) { panel.innerHTML = `<div class="empty">本次审查未检索到 RAG chunks。</div>`; return; }
    panel.innerHTML = chunks.slice(0, 30).map((c, i) => `
      <div style="padding:12px 0;border-bottom:1px solid var(--divider-soft);">
        <div style="font-size:12px;color:var(--ink-48);letter-spacing:-0.12px;">#${i + 1} · ${escapeHtml(c.source_id || c.id || "")} · score ${c.score != null ? c.score.toFixed ? c.score.toFixed(3) : c.score : "—"}</div>
        <div style="font-size:13px;color:var(--ink-80);margin-top:6px;line-height:1.5;">${escapeHtml(((c.text || c.content || "") + "").slice(0, 320))}…</div>
      </div>`).join("");
    return;
  }
  if (tab === "agent-branches") {
    const branches = lr.agent_branches || [];
    if (!branches.length) { panel.innerHTML = `<div class="empty">无 Agent 分支记录。</div>`; return; }
    panel.innerHTML = branches.map((b) => `
      <div style="padding:12px 0;border-bottom:1px solid var(--divider-soft);">
        <div style="font-size:13px;font-weight:600;color:var(--ink);">${escapeHtml(b.agent || b.name || "agent")}</div>
        <div style="font-size:12px;color:var(--ink-48);margin-top:4px;">结论：${escapeHtml(verdictMeta(b.verdict).label || b.verdict || "")}</div>
        <div style="font-size:12px;color:var(--ink-80);margin-top:6px;line-height:1.5;">${escapeHtml(localizeRuleText((b.reasons || []).join(" · ")))}</div>
      </div>`).join("");
    return;
  }
  if (tab === "rule-hits") {
    const hits = lr.rule_hits || [];
    if (!hits.length) { panel.innerHTML = `<div class="empty">无规则命中记录。</div>`; return; }
    panel.innerHTML = hits.map((h) => `
      <div style="padding:12px 0;border-bottom:1px solid var(--divider-soft);">
        <div style="font-size:13px;font-weight:600;color:var(--ink);">${escapeHtml(ruleNameZh(h.rule_id || h.id || ""))}</div>
        <div style="font-size:12px;color:var(--ink-48);margin-top:4px;">${escapeHtml(verdictMeta(h.verdict).label || severityMeta(h.severity).text || h.verdict || h.severity || "")}</div>
        <div style="font-size:12px;color:var(--ink-80);margin-top:6px;line-height:1.5;">${escapeHtml(localizeRuleText(h.reason || h.text || ""))}</div>
      </div>`).join("");
    return;
  }
  panel.innerHTML = "";
}

// —— 状态机：判定 3 态 —— //
function decideState(detail) {
  if (!detail.latest_report) return "empty";
  return "default";
}

// —— 主 mount —— //
export async function mount(outlet, params) {
  ensureCss();
  const caseId = params && params.id;
  if (!caseId) {
    outlet.innerHTML = `<div style="padding:80px;color:var(--block);">缺少 Case ID。</div>`;
    return;
  }

  const html = await loadTemplate();
  outlet.innerHTML = html;
  const root = outlet.querySelector(".report-root");
  if (!root) {
    outlet.innerHTML = `<div style="padding:80px;color:var(--block);">报告模板加载失败。</div>`;
    return;
  }

  // role class
  applyRoleClass(root);

  // 拉数据
  let detail = null;
  try {
    detail = await api.cases.get(caseId);
  } catch (err) {
    return showError(root, err, caseId);
  }
  if (!detail || !detail.case) {
    return showError(root, new Error("Case 不存在"), caseId);
  }

  setShellChrome(detail.case);

  // role 切换监听（storage 跨标签 / shell.setRole 也会触发 hashchange 重新 mount）
  const storageHandler = (e) => {
    if (e.key === "rcr.role") applyRoleClass(root);
  };
  window.addEventListener("storage", storageHandler);
  // 卸载时清理（outlet 被 router 清空时不会调用，这里靠 MutationObserver 做最低限度兜底）
  const mo = new MutationObserver(() => {
    if (!document.body.contains(root)) {
      window.removeEventListener("storage", storageHandler);
      mo.disconnect();
    }
  });
  // outlet 自身 childList 变化（router.js 会 innerHTML="" 清空再重挂）就触发清理
  mo.observe(outlet, { childList: true });

  // 派发状态
  const state = decideState(detail);
  await renderState(root, detail, state);

  // 事件绑定
  bindEvents(root, detail, (nextDetail) => { detail = nextDetail; });
}

function applyRoleClass(root) {
  const role = getRole();
  root.classList.toggle("role-admin", role === "admin");
}

function showError(root, err, caseId) {
  hideAllSlots(root);
  root.querySelector('[data-slot="error"]').hidden = false;
  const title = root.querySelector('[data-slot="error-title"]');
  const detail = root.querySelector('[data-slot="error-detail"]');
  const msg = String(err && err.message ? err.message : err);
  if (/404/.test(msg)) {
    title.textContent = `Case 不存在`;
    detail.textContent = `未在数据库中找到 Case ${caseId}。可能已被删除，或链接拼写错误。`;
  } else {
    title.textContent = "报告加载失败";
    detail.textContent = msg;
  }
  root.querySelector('[data-action="back-to-cases"]').addEventListener("click", () => {
    if (window.shell && window.shell.navigate) window.shell.navigate("#/cases");
    else window.location.hash = "#/cases";
  });
}

function hideAllSlots(root) {
  ["loading", "error", "empty", "body"].forEach((k) => {
    const el = root.querySelector(`[data-slot="${k}"]`);
    if (el) {
      el.hidden = true;
      el.style.display = "none";
    }
  });
}

async function renderState(root, detail, state) {
  hideAllSlots(root);
  root.dataset.state = state;
  root.classList.remove("state-default", "state-drawer", "state-rerun", "state-empty");
  root.classList.add(`state-${state}`);

  if (state === "empty") {
    const empty = root.querySelector('[data-slot="empty"]');
    empty.hidden = false;
    empty.style.display = "";
    const continueLink = root.querySelector('[data-slot="continue-wizard"]');
    continueLink.href = `#/cases/${encodeURIComponent(detail.case.id)}/new`;
    return;
  }

  // default / rerun 都走 body
  const body = root.querySelector('[data-slot="body"]');
  body.hidden = false;
  body.style.display = "";
  const rerun = state === "rerun";
  const rerunAlert = root.querySelector('[data-slot="rerun-alert"]');
  if (rerunAlert) rerunAlert.hidden = true;

  renderStatusBar(root, detail);
  renderStatusChips(root, detail, rerun);
  renderHero(root, detail, rerun);
  renderFindings(root, extractFindings(detail.latest_report), { rerun });
  renderDrawerPanel(root, detail, "timeline");
}

function bindEvents(root, detail, updateDetail) {
  // 下载 PDF
  const pdfBtn = root.querySelector('[data-action="download-pdf"]');
  if (pdfBtn) {
    pdfBtn.addEventListener("click", () => {
      pdfBtn.disabled = true;
      const original = pdfBtn.textContent;
      pdfBtn.textContent = "正在生成报告…";
      try {
        window.open(`/api/cases/${encodeURIComponent(detail.case.id)}/report.pdf`, "_blank");
      } catch (_) {}
      setTimeout(() => { pdfBtn.disabled = false; pdfBtn.textContent = original; }, 3000);
    });
  }

  const backBtn = root.querySelector('[data-action="back-to-board"]');
  if (backBtn) {
    backBtn.addEventListener("click", () => {
      if (window.shell && window.shell.navigate) window.shell.navigate("#/cases");
      else window.location.hash = "#/cases";
    });
  }

  // 抽屉
  const toggleBtn = root.querySelector('[data-action="toggle-drawer"]');
  const closeBtn = root.querySelector('[data-action="close-drawer"]');
  if (toggleBtn) toggleBtn.addEventListener("click", () => root.classList.toggle("drawer-open"));
  if (closeBtn) closeBtn.addEventListener("click", () => root.classList.remove("drawer-open"));

  // tabs
  const tabsHost = root.querySelector('[data-slot="drawer-tabs"]');
  if (tabsHost) {
    tabsHost.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-tab]");
      if (!btn) return;
      tabsHost.querySelectorAll("button[data-tab]").forEach((b) => b.classList.toggle("on", b === btn));
      renderDrawerPanel(root, detail, btn.dataset.tab);
    });
  }

  // 时间线节点点击：占位高亮
  root.addEventListener("click", (e) => {
    const node = e.target.closest(".tl-node");
    if (node) {
      root.querySelectorAll(".tl-node").forEach((n) => n.classList.toggle("curr-highlight", n === node));
    }
  });

  // 查看证据 → 管理员才走（CSS 已经隐藏 client 端）
  root.addEventListener("click", (e) => {
    const ev = e.target.closest('[data-action="view-evidence"]');
    if (!ev) return;
    e.preventDefault();
    // 打开抽屉 + 切到 rag-evidence tab
    root.classList.add("drawer-open");
    const ragTab = root.querySelector('button[data-tab="rag-evidence"]');
    if (ragTab) {
      root.querySelectorAll("button[data-tab]").forEach((b) => b.classList.toggle("on", b === ragTab));
      renderDrawerPanel(root, detail, "rag-evidence");
    }
  });

  // 运行预审 / 重新运行预审
  const runBtn = root.querySelector('[data-action="run-review"]');
  if (runBtn) runBtn.addEventListener("click", () => triggerReview(root, detail.case.id, updateDetail));
}

async function triggerReview(root, caseId, updateDetail) {
  // 显示 runcard 子任务态
  hideAllSlots(root);
  root.querySelector('[data-slot="body"]').hidden = false;
  root.querySelector('[data-slot="rerun-progress"]').hidden = false;
  const rerunAlert = root.querySelector('[data-slot="rerun-alert"]');
  if (rerunAlert) rerunAlert.hidden = true;

  try {
    await api.cases.runReview(caseId);
  } catch (err) {
    return showError(root, err, caseId);
  }
  // 拉新数据并重渲染
  let detail = null;
  try {
    detail = await api.cases.get(caseId);
  } catch (err) {
    return showError(root, err, caseId);
  }
  root.querySelector('[data-slot="rerun-progress"]').hidden = true;
  const state = decideState(detail);
  await renderState(root, detail, state);
  if (typeof updateDetail === "function") updateDetail(detail);
  bindEvents(root, detail, updateDetail);
  if (window.shell && window.shell.refreshCases) window.shell.refreshCases();
}

export default { mount };
