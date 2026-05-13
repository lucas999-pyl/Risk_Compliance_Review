// runner.js — Step 5 子任务进度驱动。
// 后端 run-review 当前同步返回（一次请求等到结果），所以我们用乐观节奏
// 在前端串起 6 行子任务的视觉点亮：发起请求 → 立即开始第 1 步动画 →
// 请求结束（或失败）后把剩余步骤一次"快进"完成（或停在失败步）。
// 这样既不假造数据，也给用户清晰的进度感知。

import { api } from "/static/js/api.js";

export const SUB_TASKS = [
  { id: "identify",  label: "识别物料与组分" },
  { id: "retrieve",  label: "检索匹配规则（向量召回 + Rerank）" },
  { id: "agents",    label: "多 Agent 分支分析" },
  { id: "merge",     label: "主审合并 · 形成结论草稿" },
  { id: "qc",        label: "交叉质检 · 一致性校验" },
  { id: "report",    label: "生成客户报告" },
];

// state: "pending" | "running" | "done" | "failed"
export function makeRunState() {
  return SUB_TASKS.map((t) => ({ ...t, state: "pending", elapsedMs: 0 }));
}

// onUpdate(rows, overallPct) — 主页绘制由 steps.js 提供。
// 行为：每 ~700ms 推进当前 running 行的 elapsed；后端返回时把
// 剩余行一次性快速点亮（每 180ms 一行）。
export async function runReview(caseId, onUpdate) {
  const rows = makeRunState();
  let cancelled = false;
  const cancel = () => { cancelled = true; };

  function emit() {
    const doneCt = rows.filter((r) => r.state === "done").length;
    const runIdx = rows.findIndex((r) => r.state === "running");
    const partial = runIdx >= 0 ? 0.5 : 0;
    const pct = Math.min(100, Math.round(((doneCt + partial) / rows.length) * 100));
    onUpdate && onUpdate(rows, pct);
  }

  rows[0].state = "running";
  emit();

  // 节奏动画：每 700ms 累加 elapsed；不到 done 时切到下一行
  const tickHandle = setInterval(() => {
    if (cancelled) return;
    const i = rows.findIndex((r) => r.state === "running");
    if (i < 0) return;
    rows[i].elapsedMs += 700;
    // 前 3 行最长 2.5s 自动切到下一行（让 UI 动起来），后 3 行等接口返回
    if (i < 3 && rows[i].elapsedMs >= 2500) {
      rows[i].state = "done";
      if (rows[i + 1]) rows[i + 1].state = "running";
    }
    emit();
  }, 700);

  let resp = null;
  let err = null;
  try {
    resp = await api.cases.runReview(caseId, {});
  } catch (e) {
    err = e;
  }
  clearInterval(tickHandle);
  if (cancelled) return { cancelled: true };

  if (err) {
    // 把当前 running 行标 failed，其余 pending 保留
    const i = rows.findIndex((r) => r.state === "running");
    if (i >= 0) rows[i].state = "failed";
    else if (rows[0]) rows[0].state = "failed";
    emit();
    throw err;
  }

  // 后端已完成 → 把剩余行依次快进点亮，每 180ms 一行
  for (let i = 0; i < rows.length; i++) {
    if (rows[i].state !== "done") {
      // 先确保只有当前行 running 一次，再标 done
      rows[i].state = "done";
      // 同步把下一行变 running，给后续步骤短暂动画感
      if (rows[i + 1] && rows[i + 1].state === "pending") {
        // do nothing — 直接在下一次循环点亮
      }
      emit();
      await new Promise((r) => setTimeout(r, 180));
    }
  }

  return { cancelled: false, response: resp, cancel };
}
