// router.js — 极简 hash router；唯一活动路由 mount 到 #route-outlet。
// pattern 形如 "#/cases" / "#/cases/:id" / "#/cases/:id/new" / "#/admin/kb" / "#/admin/cases/:id/trace"
// mountFn: async (outlet, params) => { ... } params: { ...named, query }

const routes = [];
let currentMountId = 0;

function compile(pattern) {
  const cleaned = pattern.replace(/^#/, "");
  const parts = cleaned.split("/").filter(Boolean);
  const keys = [];
  const segments = parts.map((seg) => {
    if (seg.startsWith(":")) {
      keys.push(seg.slice(1));
      return "([^/]+)";
    }
    return seg.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  });
  const regex = new RegExp("^#/" + segments.join("/") + "/?$");
  return { regex, keys };
}

export function registerRoute(pattern, mountFn) {
  const { regex, keys } = compile(pattern);
  routes.push({ pattern, regex, keys, mountFn });
}

export function navigate(hash) {
  if (typeof hash !== "string") return;
  if (!hash.startsWith("#")) hash = "#" + hash;
  if (window.location.hash === hash) {
    dispatch();
  } else {
    window.location.hash = hash;
  }
}

export function getCurrentRoute() {
  return window.location.hash || "#/cases";
}

function parseQuery(raw) {
  const out = {};
  if (!raw) return out;
  const usp = new URLSearchParams(raw);
  usp.forEach((v, k) => {
    out[k] = v;
  });
  return out;
}

function matchRoute(fullHash) {
  const [path, queryRaw] = fullHash.split("?");
  for (const r of routes) {
    const m = path.match(r.regex);
    if (m) {
      const params = { query: parseQuery(queryRaw) };
      r.keys.forEach((k, i) => {
        params[k] = decodeURIComponent(m[i + 1]);
      });
      // 也把常用 query 提到顶层方便取
      if (params.query.step) params.step = params.query.step;
      return { route: r, params };
    }
  }
  return null;
}

async function dispatch() {
  const hash = getCurrentRoute();
  const outlet = document.getElementById("route-outlet");
  if (!outlet) return;
  const myId = ++currentMountId;
  outlet.innerHTML = "";
  const matched = matchRoute(hash);
  if (!matched) {
    outlet.innerHTML = `<div style="padding:64px 80px;color:var(--ink-48);">未找到路由：${hash}</div>`;
    return;
  }
  try {
    await matched.route.mountFn(outlet, matched.params);
  } catch (err) {
    if (myId !== currentMountId) return;
    console.error("[router] mount failed:", err);
    outlet.innerHTML = `<div style="padding:64px 80px;color:var(--block);">页面加载失败：${err && err.message ? err.message : err}</div>`;
  }
  window.dispatchEvent(new CustomEvent("router:changed", { detail: { hash, params: matched.params } }));
}

export function startRouter() {
  window.addEventListener("hashchange", dispatch);
  dispatch();
}
