from __future__ import annotations

import asyncio
import html
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


CUSTOMER_REPORT_KEYS = {
    "schema_version",
    "report_metadata",
    "case_profile",
    "verdict",
    "verdict_label",
    "executive_summary",
    "summary",
    "review_scenario",
    "selected_checks",
    "review_scope",
    "limited_checks",
    "blocked_checks",
    "supplement_actions",
    "customer_supplement_actions",
    "issue_groups",
    "compliant_summary",
    "next_actions",
    "evidence_policy",
    "limitations",
    "technical_reference",
    "disclaimer",
}


def latest_customer_report(latest_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not latest_payload:
        return None
    report = latest_payload.get("customer_report", latest_payload)
    if not isinstance(report, dict):
        return None
    return sanitize_customer_report(report)


def sanitize_customer_report(report: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in report.items() if key in CUSTOMER_REPORT_KEYS}


def customer_report_filename(report: dict[str, Any], suffix: str) -> str:
    case_id = report.get("report_metadata", {}).get("case_id") or report.get("case_profile", {}).get("case_id") or "case"
    safe_case = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(case_id))
    return f"customer-compliance-report-{safe_case}.{suffix}"


def render_customer_report_html(report: dict[str, Any]) -> str:
    report = sanitize_customer_report(report)
    case_profile = report.get("case_profile", {})
    metadata = report.get("report_metadata", {})
    summary = report.get("executive_summary", {})
    review_scope = report.get("review_scope", {})
    issue_groups = report.get("issue_groups", [])
    verdict = str(report.get("verdict", "needs_review"))
    verdict_class = {
        "pass": "ok",
        "needs_review": "review",
        "needs_supplement": "supplement",
        "not_approved": "bad",
    }.get(verdict, "review")
    metrics = [
        ("问题总数", summary.get("issue_count", 0)),
        ("补件事项", summary.get("supplement_count", 0)),
        ("复核事项", summary.get("needs_review_count", 0)),
        ("不建议准入", summary.get("not_approved_count", 0)),
    ]
    selected_checks = report.get("selected_checks", [])
    html_body = f"""
      <header class="report-header">
        <div>
          <p class="eyebrow">客户合规预审报告</p>
          <h1>{_e(case_profile.get("title", "未命名 Case"))}</h1>
          <p>{_e(report.get("summary", ""))}</p>
        </div>
        <div class="verdict {verdict_class}">
          <span>预审结论</span>
          <strong>{_e(report.get("verdict_label", verdict))}</strong>
        </div>
      </header>

      <section class="meta-grid">
        <div><span>Case ID</span><strong>{_e(metadata.get("case_id") or case_profile.get("case_id") or "-")}</strong></div>
        <div><span>Run ID</span><strong>{_e(metadata.get("run_id") or "-")}</strong></div>
        <div><span>生成时间</span><strong>{_e(metadata.get("generated_at") or "-")}</strong></div>
        <div><span>目标市场</span><strong>{_e("、".join(case_profile.get("target_markets", [])) or "-")}</strong></div>
      </section>

      <section class="metric-strip">
        {''.join(f'<div><span>{_e(label)}</span><strong>{_e(value)}</strong></div>' for label, value in metrics)}
      </section>

      <section>
        <h2>审查范围</h2>
        <p>{_e(review_scope.get("message", "本次报告未返回独立审查范围说明。"))}</p>
        <div class="check-list">
          {''.join(f'<span>{_e(item.get("label", item.get("id", "")))}</span>' for item in selected_checks)}
        </div>
      </section>

      <section>
        <h2>问题分组</h2>
        {_render_issue_groups(issue_groups, report.get("compliant_summary", ""))}
      </section>

      <section class="two-col">
        <div>
          <h2>补件动作</h2>
          {_render_list(report.get("customer_supplement_actions") or [_action_text(item) for item in report.get("supplement_actions", [])], "当前没有客户级补件动作。")}
        </div>
        <div>
          <h2>下一步</h2>
          {_render_list(report.get("next_actions", []), "进入内部准入审批或人工复核流程。")}
        </div>
      </section>

      <section class="two-col">
        <div>
          <h2>限制说明</h2>
          {_render_list(report.get("limitations", []), "本报告仅覆盖已上传资料和所选检查项。")}
        </div>
        <div>
          <h2>技术边界</h2>
          <p>客户报告保留规则编号、规则原文、用户资料原文/识别结果、影响说明和整改建议；检索切片明细、内部排序分数、智能体分支原始输出和执行链路调试 JSON 保留在管理端。</p>
        </div>
      </section>

      <footer>{_e(report.get("disclaimer", "本结果为 AI 辅助合规预审，不替代最终法规、法律或 EHS 审批意见。"))}</footer>
    """
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>客户合规预审报告</title>
  <style>{_report_css()}</style>
</head>
<body>
  <main class="report-page">
    {html_body}
  </main>
</body>
</html>
"""


def render_customer_report_pdf(report: dict[str, Any]) -> bytes:
    html_text = render_customer_report_html(report)
    playwright_error: Exception | None = None
    try:
        return _render_customer_report_pdf_with_playwright(html_text)
    except Exception as exc:
        playwright_error = exc
    try:
        return _render_customer_report_pdf_with_chrome(html_text)
    except Exception as chrome_exc:
        raise RuntimeError(
            "PDF renderer is unavailable. Install Playwright with `python -m pip install -e \".[reports]\"` "
            "and `python -m playwright install chromium`, or install Chrome/Edge for the fallback renderer."
        ) from chrome_exc if playwright_error is not None else chrome_exc


def _render_customer_report_pdf_with_playwright(html_text: str) -> bytes:
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as tmp_dir:
        html_path = Path(tmp_dir) / "report.html"
        html_path.write_text(html_text, encoding="utf-8")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.goto(html_path.as_uri(), wait_until="load")
            pdf = page.pdf(
                format="A4",
                print_background=True,
                display_header_footer=False,
                margin={"top": "10mm", "right": "10mm", "bottom": "10mm", "left": "10mm"},
            )
            browser.close()
            return pdf


def _render_customer_report_pdf_with_chrome(html_text: str) -> bytes:
    chrome_path = _find_system_chromium()
    if not chrome_path:
        raise RuntimeError("No system Chrome or Edge executable was found.")
    with tempfile.TemporaryDirectory() as tmp_dir:
        html_path = Path(tmp_dir) / "report.html"
        pdf_path = Path(tmp_dir) / "report.pdf"
        html_path.write_text(html_text, encoding="utf-8")
        command = [
            chrome_path,
            "--headless=new",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
            f"--print-to-pdf={pdf_path}",
            "--print-to-pdf-no-header",
            "--no-pdf-header-footer",
            html_path.as_uri(),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "Chrome PDF renderer failed.").strip())
        pdf = pdf_path.read_bytes()
        if not pdf.startswith(b"%PDF-"):
            raise RuntimeError("Chrome PDF renderer did not produce a valid PDF.")
        return pdf


def _find_system_chromium() -> str | None:
    for executable in ("chrome", "chrome.exe", "msedge", "msedge.exe", "google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(executable)
        if found:
            return found
    candidates = [
        Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe",
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


async def render_customer_report_pdf_async(report: dict[str, Any]) -> bytes:
    return await asyncio.to_thread(render_customer_report_pdf, report)


def _render_issue_groups(groups: list[dict[str, Any]], compliant_summary: str) -> str:
    if not groups:
        return f'<article class="issue-empty"><strong>无不合格、复核或补件事项</strong><p>{_e(compliant_summary or "客户报告仅列示不合格、复核和补件事项。")}</p></article>'
    rendered = []
    for group in groups:
        items = group.get("items", [])
        rendered.append(
            f"""
            <article class="issue-group">
              <div class="issue-group-head">
                <h3>{_e(group.get("label", group.get("id", "问题分组")))}</h3>
                <span>{_e(group.get("issue_count", len(items)))} 项</span>
              </div>
              {''.join(_render_issue_item(item) for item in items)}
            </article>
            """
        )
    return "".join(rendered)


def _render_issue_item(item: dict[str, Any]) -> str:
    owner = "供应商/EHS/法规复核人" if item.get("requires_human_review", True) else "供应商/业务负责人"
    return f"""
      <div class="issue-item { _e(item.get("status", "needs_review")) }">
        <div class="issue-title">
          <strong>{_e(item.get("id", ""))} - {_e(item.get("reason", ""))}</strong>
          <span>{_e(item.get("status_label", item.get("status", "")))} / {_e(item.get("severity", ""))}</span>
        </div>
        <dl>
          <dt>依据</dt><dd>{_e(item.get("rule_text", ""))}</dd>
          <dt>资料原文/识别结果</dt><dd>{_e(item.get("user_text", ""))}</dd>
          <dt>影响</dt><dd>{_e(item.get("impact", ""))}</dd>
          <dt>整改建议</dt><dd>{_e(item.get("recommendation", ""))}</dd>
          <dt>责任方</dt><dd>{_e(owner)}</dd>
        </dl>
      </div>
    """


def _render_list(items: list[Any], empty: str) -> str:
    values = [str(item) for item in items if str(item).strip()]
    if not values:
        values = [empty]
    return "<ul>" + "".join(f"<li>{_e(item)}</li>" for item in values) + "</ul>"


def _action_text(action: dict[str, Any]) -> str:
    return str(action.get("action") or action.get("reason") or "").strip()


def _e(value: Any) -> str:
    if value is None:
        value = ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    return html.escape(str(value), quote=True)


def _report_css() -> str:
    return """
      :root {
        color-scheme: light;
        --ink: #17211d;
        --muted: #5d6d66;
        --line: #d8e0dc;
        --panel: #ffffff;
        --paper: #f5f7f4;
        --brand: #246b54;
        --ok: #067647;
        --warn: #a15c06;
        --bad: #b42318;
        --ok-bg: #dcfae6;
        --warn-bg: #fff4df;
        --bad-bg: #fee4e2;
      }
      * { box-sizing: border-box; }
      html { background: var(--paper); }
      body {
        margin: 0;
        background: var(--paper);
        color: var(--ink);
        font-family: "Segoe UI", "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif;
        line-height: 1.55;
        font-size: 13px;
      }
      .report-page {
        max-width: 1040px;
        margin: 0 auto;
        padding: 28px;
        background: var(--panel);
      }
      .report-header {
        display: grid;
        grid-template-columns: minmax(0, 1fr) 220px;
        gap: 18px;
        align-items: stretch;
        border-bottom: 2px solid var(--ink);
        padding-bottom: 18px;
      }
      .eyebrow {
        margin: 0 0 6px;
        color: var(--brand);
        font-weight: 800;
      }
      h1, h2, h3, p { margin-top: 0; }
      h1 { font-size: 25px; line-height: 1.2; margin-bottom: 10px; }
      h2 { font-size: 17px; border-bottom: 1px solid var(--line); padding-bottom: 6px; margin-bottom: 10px; }
      h3 { font-size: 14px; margin: 0; }
      section { margin-top: 20px; break-inside: avoid; }
      .verdict {
        display: grid;
        gap: 8px;
        align-content: center;
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 14px;
      }
      .verdict strong { font-size: 24px; }
      .verdict.ok { background: var(--ok-bg); color: var(--ok); }
      .verdict.review, .verdict.supplement { background: var(--warn-bg); color: var(--warn); }
      .verdict.bad { background: var(--bad-bg); color: var(--bad); }
      .meta-grid, .metric-strip {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 8px;
        margin-top: 16px;
      }
      .meta-grid div, .metric-strip div {
        border: 1px solid var(--line);
        border-radius: 6px;
        padding: 9px;
        min-width: 0;
      }
      span { color: var(--muted); }
      .meta-grid strong, .metric-strip strong {
        display: block;
        overflow-wrap: anywhere;
      }
      .metric-strip strong { font-size: 22px; }
      .check-list {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
      }
      .check-list span {
        border: 1px solid var(--line);
        border-radius: 999px;
        padding: 3px 8px;
        color: var(--ink);
      }
      .issue-group {
        border: 1px solid var(--line);
        border-radius: 8px;
        margin-bottom: 12px;
        overflow: hidden;
        break-inside: avoid;
      }
      .issue-group-head {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        background: #f8faf8;
        padding: 10px 12px;
        border-bottom: 1px solid var(--line);
      }
      .issue-item { padding: 12px; border-bottom: 1px solid var(--line); break-inside: avoid; }
      .issue-item:last-child { border-bottom: 0; }
      .issue-title {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 8px;
      }
      dl {
        display: grid;
        grid-template-columns: 120px minmax(0, 1fr);
        gap: 5px 10px;
        margin: 0;
      }
      dt { color: var(--muted); font-weight: 700; }
      dd { margin: 0; overflow-wrap: anywhere; }
      .two-col {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 18px;
        align-items: start;
      }
      ul { margin: 0; padding-left: 18px; }
      footer {
        margin-top: 24px;
        padding-top: 12px;
        border-top: 1px solid var(--line);
        color: var(--muted);
        font-size: 12px;
      }
      @page {
        size: A4;
        margin: 10mm;
      }
      @media (max-width: 760px) {
        .report-page { padding: 16px; }
        .report-header, .meta-grid, .metric-strip, .two-col { grid-template-columns: 1fr; }
        dl { grid-template-columns: 1fr; }
        .issue-title { display: grid; }
      }
      @media print {
        html,
        body {
          width: 190mm;
          min-height: auto;
          background: #fff;
          print-color-adjust: exact;
          -webkit-print-color-adjust: exact;
        }
        body {
          font-size: 11px;
          line-height: 1.42;
        }
        .report-page {
          width: 190mm;
          max-width: none;
          margin: 0;
          padding: 0;
        }
        .report-header {
          display: grid;
          grid-template-columns: minmax(0, 1fr) 55mm;
          gap: 10mm;
          padding-bottom: 8mm;
        }
        h1 { font-size: 21px; }
        h2 { font-size: 14px; }
        section { margin-top: 9mm; }
        .meta-grid,
        .metric-strip {
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 3mm;
          margin-top: 7mm;
        }
        .meta-grid div,
        .metric-strip div,
        .verdict {
          padding: 3mm;
        }
        .metric-strip strong,
        .verdict strong {
          font-size: 18px;
        }
        .issue-item,
        .two-col,
        .meta-grid div,
        .metric-strip div {
          page-break-inside: avoid;
          break-inside: avoid;
        }
        .issue-group {
          page-break-inside: auto;
          break-inside: auto;
        }
        .issue-group-head {
          page-break-after: avoid;
          break-after: avoid;
        }
        .issue-item {
          padding: 4mm;
        }
        dl {
          display: grid;
          grid-template-columns: 34mm minmax(0, 1fr);
          gap: 2mm 3mm;
        }
      }
    """
