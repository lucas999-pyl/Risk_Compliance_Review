// pages/wizard/index.js — Wizard 5 步入口
//
// 通过 shell.js 的 PAGE_MAP 注册 #/cases/new → mount(this)。
// 第二条路由 #/cases/:id/new 不在 PAGE_MAP 中，本模块在加载时
// 用 registerRoute 自行补注册，复用同一个 mount。
// 切路由时 shell 会清空 #route-outlet，无需自卸载。

import { registerRoute, navigate } from "/static/js/router.js";
import { renderStep1, renderStep2, renderStep3, renderStep4, renderStep5 } from "./steps.js";

// 注入页 CSS（一次）
function ensureCss() {
  const href = "/static/pages/wizard/wizard.css";
  if (document.querySelector(`link[data-wizard-css]`)) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  link.setAttribute("data-wizard-css", "1");
  document.head.appendChild(link);
}

// 跨 mount 共享的 ctx（按 caseId 关联）。
// caseId 变化时清空 draft/precheck/scope/runState。
const ctxStore = {
  // key: caseId 或 "__draft__"
  byCase: new Map(),
};

function makeCtx(caseId) {
  return {
    caseId: caseId || null,
    draft: {
      title: "",
      scenario: "market_access",
      markets: ["EU"], // 默认推荐 EU（D44）
    },
    precheck: null,
    documents: [],
    scope: null,     // Set<string>，Step 4 首次进入时初始化
    runState: null,
  };
}

function getCtx(caseId) {
  const key = caseId || "__draft__";
  if (!ctxStore.byCase.has(key)) ctxStore.byCase.set(key, makeCtx(caseId));
  const ctx = ctxStore.byCase.get(key);
  if (caseId && !ctx.caseId) ctx.caseId = caseId;
  return ctx;
}

// —— mount —— //

export async function mount(outlet, params) {
  ensureCss();
  const step = String((params && params.step) || (params && params.query && params.query.step) || "1");
  const caseId = (params && params.id) || null;
  const ctx = getCtx(caseId);

  switch (step) {
    case "1": return renderStep1(outlet, ctx);
    case "2": return renderStep2(outlet, ctx);
    case "3": return renderStep3(outlet, ctx);
    case "4": return renderStep4(outlet, ctx);
    case "5": return renderStep5(outlet, ctx);
    default:
      outlet.innerHTML = `<div class="wzbody"><h1>未知 Step</h1>
        <div class="lead">step=${step} 不识别。</div></div>`;
      return;
  }
}

// 自行注册带 :id 的 wizard 路由（shell.js 的 PAGE_MAP 只注册了 #/cases/new）
// 这里加上 #/cases/:id/new，复用同一个 mount。
// 注意：模块只加载一次（shell.js loaded Map 缓存），所以这里只会执行一次。
registerRoute("#/cases/:id/new", async (outlet, p) => mount(outlet, p));

// 入口路由 #/cases/new 已由 shell.js 注册，且会调用本模块的 mount。
// 但当用户直接刷新 #/cases/:id/new 时，shell 找不到匹配路由
// （PAGE_MAP 不含这条），所以由我们 registerRoute 补上即可。
// 如果用户刷新前从未访问过 wizard，则模块尚未加载，下面的 fallback
// 也无法生效——但 shell.js 在 boot 时把所有 PAGE_MAP 路由注册了，
// 而 #/cases/:id/new 不在 PAGE_MAP 里 → router 会显示 "未找到路由"。
// 兜底方案：在 shell 启动后立刻 preload 本模块（由 shell 自动处理 #/cases/new 的初始加载完成此事）。

export default { mount };
