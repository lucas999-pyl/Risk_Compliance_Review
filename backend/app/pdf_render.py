"""化工合规审查报告 · 后端 PDF 渲染模块

通过 Playwright headless chromium 加载本地打印模板 URL 并 page.pdf() 出 A4 报告。

设计要点：
- 单例 chromium browser，避免每次冷启动 1-2s。
- 打印模板 + CSS 静态化在 backend/app/static/print/ 下，直接由 chromium 经 HTTP
  访问（http://127.0.0.1:<port>/print/cases/<case_id>/report），既能转 PDF，也能
  人工浏览器打开调试。
- 占位符替换走 str.replace（项目无 Jinja2 依赖）。HTML 安全：所有用户/数据库内容
  在写入模板前必须经 _esc() 转义。
- 失败抛业务异常，由路由层 catch 转 HTTP 错误码。

仅渲染客户视角内容（spec §8.5）：禁出现 RAG TopK / 切块 / Agent 分支 / 规则库
版本号 / Manifest 指纹。
"""
from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.store import SQLiteStore


class PDFRendererUnavailable(RuntimeError):
    """Playwright / chromium 不可用（未装、driver 损坏、启动失败等）。"""


class CaseNotReady(RuntimeError):
    """Case 未完成预审或 latest_report 缺失。"""


# verdict_zh 映射 —— 严格按 HANDOFF §4
_VERDICT_ZH = {
    "pass": "可审",
    "needs_review": "需复核",
    "needs_supplement": "待补",
    "not_approved": "不可审",
}

# verdict_css 选择灰度三重编码的 badge 样式
_VERDICT_CSS = {
    "pass": "pass",
    "needs_review": "warn",
    "needs_supplement": "supp",
    "not_approved": "block",
}

# 严重度 → badge css 类（灰度三重编码）
_SEVERITY_CSS = {
    "blocking": "block",
    "high": "block",
    "critical": "block",
    "needs_review": "warn",
    "medium": "warn",
    "low": "warn",
    "needs_supplement": "supp",
}

# 状态 → 中文展示
_STATUS_ZH = {
    "needs_supplement": "待补",
    "needs_review": "需复核",
    "not_approved": "不可审",
    "pass": "可审",
}

# 场景 → 中文 label（与 factory.REVIEW_SCENARIO_LABELS_FOR_FACTORY 对齐，但本模块
# 独立维护避免反向依赖）
_SCENARIO_LABELS = {
    "market_access": "市场准入审查",
    "substitution": "替代物料评估",
    "supplier_intake": "供应商资料准入",
    "process_introduction": "工艺导入风险评估",
    "storage_safety": "储运与现场安全评估",
}

# document_type → 中文 label
_DOC_TYPE_LABELS = {
    "sds": "SDS · 安全技术说明书",
    "formula": "配方 / 成分明细",
    "process": "工艺说明",
    "process_flow": "工艺说明",
    "test_report": "检测报告",
    "label": "标签",
    "certificate": "资质证明",
    "supplier": "供应商资料",
    "document": "文档",
}

_TEMPLATE_DIR = Path(__file__).parent / "static" / "print"
_TEMPLATE_HTML = _TEMPLATE_DIR / "case-report.html"


# --------------------------------------------------------------------------- #
# Playwright 单例 browser
# --------------------------------------------------------------------------- #

_browser_lock = asyncio.Lock()
_browser: Any = None
_playwright_ctx: Any = None


async def _get_browser() -> Any:
    """惰性启动单例 chromium。失败抛 PDFRendererUnavailable。"""
    global _browser, _playwright_ctx
    if _browser is not None:
        return _browser
    async with _browser_lock:
        if _browser is not None:
            return _browser
        try:
            from playwright.async_api import async_playwright  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise PDFRendererUnavailable("playwright 未安装") from exc
        try:
            _playwright_ctx = await async_playwright().start()
            _browser = await _playwright_ctx.chromium.launch(
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
        except Exception as exc:  # pragma: no cover
            raise PDFRendererUnavailable(f"chromium 启动失败: {exc}") from exc
    return _browser


async def shutdown_pdf_renderer() -> None:
    """关闭单例 browser（FastAPI shutdown 钩子可调用，可选）。"""
    global _browser, _playwright_ctx
    try:
        if _browser is not None:
            await _browser.close()
    except Exception:  # pragma: no cover
        pass
    try:
        if _playwright_ctx is not None:
            await _playwright_ctx.stop()
    except Exception:  # pragma: no cover
        pass
    _browser = None
    _playwright_ctx = None


# --------------------------------------------------------------------------- #
# 模板填充
# --------------------------------------------------------------------------- #

def _esc(value: Any) -> str:
    """HTML 安全转义（一切来源于数据库 / 用户的字符串都必须经过这里）。"""
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _target_market_text(markets: list[str] | None) -> str:
    if not markets:
        return "—"
    return " / ".join(markets)


def _scenario_label(scenario: str | None) -> str:
    if not scenario:
        return "—"
    return _SCENARIO_LABELS.get(scenario, scenario)


def _verdict_summary(customer_report: dict[str, Any]) -> str:
    summary = customer_report.get("summary") or customer_report.get("executive_summary") or ""
    if isinstance(summary, list):
        summary = "；".join(str(item) for item in summary if item)
    return str(summary or "").strip() or "本案已完成预审，详见以下各章节。"


def _format_documents(documents: list[dict[str, Any]]) -> str:
    if not documents:
        return '<div class="empty-line">本案未上传可读资料。</div>'
    rows: list[str] = []
    for doc in documents:
        filename = _esc(doc.get("filename") or "—")
        doc_type = doc.get("document_type") or "document"
        type_label = _DOC_TYPE_LABELS.get(doc_type, _esc(doc_type))
        # 解析状态做 meta 后缀
        parse_status = doc.get("parse_status")
        text_source = doc.get("text_source")
        meta_bits = []
        if text_source and text_source != "missing":
            meta_bits.append("已解析")
        if parse_status == "ok":
            meta_bits.append("高置信")
        elif parse_status == "needs_manual_review":
            meta_bits.append("需人工确认")
        elif parse_status:
            meta_bits.append(_esc(parse_status))
        meta_text = " · ".join(meta_bits) if meta_bits else "—"
        rows.append(
            f'<div class="item">'
            f'<div class="nm">{filename}<small>{_esc(type_label)}</small></div>'
            f'<div class="meta">{_esc(meta_text)}</div>'
            f'</div>'
        )
    return "\n".join(rows)


def _severity_css(value: str | None) -> str:
    if not value:
        return ""
    return _SEVERITY_CSS.get(value, "warn")


def _severity_label(severity: str | None, status: str | None) -> str:
    # 优先用 severity，回退 status
    sev_map = {
        "blocking": "严重 · 阻断",
        "high": "严重",
        "critical": "严重 · 阻断",
        "medium": "需复核",
        "low": "需复核",
    }
    if severity and severity in sev_map:
        return sev_map[severity]
    if status:
        return _STATUS_ZH.get(status, status)
    return "需复核"


def _quote(text: str | None) -> str:
    if not text:
        return ""
    return _esc(text).strip()


def _format_findings(customer_report: dict[str, Any]) -> tuple[str, int]:
    """返回 (html, total_count)。把 issue_groups 拍平按整体顺序编号 01..N。"""
    groups = customer_report.get("issue_groups") or []
    items_flat: list[dict[str, Any]] = []
    for group in groups:
        for item in group.get("items", []) or []:
            items_flat.append({**item, "_group_label": group.get("label")})

    if not items_flat:
        return (
            '<div class="empty-line">本次预审未识别需要客户处理的不合规事项。</div>',
            0,
        )

    rendered: list[str] = []
    for index, item in enumerate(items_flat, 1):
        num = f"{index:02d}"
        rule_id = item.get("rule_id") or (item.get("rule") or {}).get("id") or "—"
        rule_text = (
            item.get("rule_text")
            or (item.get("rule") or {}).get("text")
            or ""
        )
        user_text = (
            item.get("user_text")
            or (item.get("source") or {}).get("text")
            or ""
        )
        recommendation = item.get("recommendation") or item.get("reason") or "—"
        severity = item.get("severity")
        status = item.get("status")
        sev_css = _severity_css(severity or status)
        sev_label = _severity_label(severity, status)
        group_label = item.get("_group_label") or item.get("category_label") or ""

        # 组装 finding row
        rule_block = ""
        if rule_id and rule_id != "—":
            rule_block = f'<span class="rid">{_esc(rule_id)}</span>'
        rule_quote = (
            f'<span class="quote">"{_quote(rule_text)}"</span>'
            if rule_text else ""
        )
        user_block = (
            f'<span class="quote">{_quote(user_text)}</span>'
            if user_text else '<span class="quote">资料中未提供相关原文。</span>'
        )

        category_line = ""
        if group_label:
            category_line = (
                f'<div class="row"><div class="k">检查项</div>'
                f'<div class="v">{_esc(group_label)}</div></div>'
            )

        rendered.append(
            f'<div class="pf-find">'
            f'  <div class="num">{num}</div>'
            f'  <div class="body">'
            f'    {category_line}'
            f'    <div class="row"><div class="k">违反规则</div>'
            f'      <div class="v">{rule_block}{rule_quote}</div></div>'
            f'    <div class="row"><div class="k">用户原文</div>'
            f'      <div class="v">{user_block}</div></div>'
            f'    <div class="row"><div class="k">改进建议</div>'
            f'      <div class="v">{_esc(recommendation)}</div></div>'
            f'  </div>'
            f'  <div class="sev">'
            f'    <span class="sev-badge {sev_css}">'
            f'      <span class="glyph {sev_css}"></span>{_esc(sev_label)}'
            f'    </span>'
            f'  </div>'
            f'</div>'
        )

    return ("\n".join(rendered), len(items_flat))


def _render_print_template(case: dict[str, Any], payload: dict[str, Any]) -> str:
    """把模板 case-report.html 内的 {{ ... }} 占位填上，返回完整 HTML 字符串。

    使用 str.replace（无外部模板引擎依赖）。所有写入值已经过 _esc() 转义或本身是
    我们自己构造的 HTML 片段（documents_html / findings_html）。
    """
    customer_report = payload.get("customer_report") or {}
    verdict = (
        customer_report.get("verdict")
        or case.get("latest_verdict")
        or "needs_review"
    )
    verdict_zh = _VERDICT_ZH.get(verdict, verdict or "需复核")
    verdict_css = _VERDICT_CSS.get(verdict, "warn")

    documents_list = customer_report.get("documents")
    # customer_report 通常不带原始文件清单；fallback：直接接 payload['uploaded_documents']
    if not documents_list:
        documents_list = payload.get("uploaded_documents") or payload.get("documents") or []
    # 兜底：拿不到时通过外部存储传进来 —— 见 render_case_report_pdf 在调用前注入
    documents_html = _format_documents(documents_list or [])

    findings_html, finding_count = _format_findings(customer_report)
    findings_heading = (
        f"不合规事项 · 共 {finding_count} 项"
        if finding_count
        else "不合规事项"
    )

    target_market_text = _target_market_text(case.get("target_markets") or [])

    review_date = ""
    generated_at = customer_report.get("generated_at") or payload.get("generated_at")
    if generated_at:
        # generated_at 形如 '2026-05-13T08:19:01...'
        review_date = str(generated_at)[:10]
    if not review_date:
        review_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    generated_at_display = (
        str(generated_at).replace("T", " ")[:16] if generated_at
        else datetime.now().strftime("%Y-%m-%d %H:%M")
    )

    template_text = _TEMPLATE_HTML.read_text(encoding="utf-8")

    substitutions = {
        "{{ case_title }}": _esc(case.get("title") or "—"),
        "{{ case_id }}": _esc(case.get("id") or "—"),
        "{{ scenario_label }}": _esc(_scenario_label(case.get("review_scenario"))),
        "{{ target_market }}": _esc(target_market_text),
        "{{ review_date }}": _esc(review_date),
        "{{ verdict_zh }}": _esc(verdict_zh),
        "{{ verdict_css }}": verdict_css,  # safe: closed enum
        "{{ verdict_summary }}": _esc(_verdict_summary(customer_report)),
        "{{ documents_html }}": documents_html,
        "{{ findings_html }}": findings_html,
        "{{ findings_heading }}": _esc(findings_heading),
        "{{ generated_at_display }}": _esc(generated_at_display),
    }
    output = template_text
    for placeholder, value in substitutions.items():
        output = output.replace(placeholder, value)
    return output


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #

def build_print_html(case: dict[str, Any], payload: dict[str, Any], documents: list[dict[str, Any]] | None = None) -> str:
    """构造打印态 HTML（同步、纯字符串）。被 /print/cases/{id}/report 直接复用。"""
    # 把 store 拿到的 documents 注入到 payload 里供 _format_documents 使用
    effective_payload = dict(payload)
    if documents:
        effective_payload.setdefault("uploaded_documents", documents)
    return _render_print_template(case, effective_payload)


async def render_case_report_pdf(
    case_id: str,
    store: SQLiteStore,
    *,
    base_url: str = "http://127.0.0.1:8888",
) -> bytes:
    """加载 /print/cases/<case_id>/report 并产出 PDF 字节流。

    Args:
        case_id: 必须已存在且 store.latest_report() 返回非空。
        store: 在路由层注入；本函数不实际查数据库（仅校验 case 是否就绪），
               真正的数据库读取由 /print/cases/{id}/report 路由完成。
        base_url: 本地 uvicorn 监听地址。chromium 内部从这个 URL 拉取打印模板。

    Raises:
        CaseNotReady: case 不存在或无 latest_report。
        PDFRendererUnavailable: playwright / chromium 不可用。
    """
    case = store.get_case(case_id)
    if not case:
        raise CaseNotReady(f"case {case_id} not found")
    latest = store.latest_report(case_id)
    if not latest:
        raise CaseNotReady(f"case {case_id} has no completed review")

    browser = await _get_browser()
    page_url = f"{base_url.rstrip('/')}/cases/{case_id}/print"

    context = await browser.new_context()
    try:
        page = await context.new_page()
        try:
            response = await page.goto(page_url, wait_until="networkidle", timeout=30000)
            if response is None or not response.ok:
                status = response.status if response else "no-response"
                raise PDFRendererUnavailable(
                    f"chromium fetch {page_url} failed: status={status}"
                )
            # A4 + 25mm/20mm 边距 + 背景图
            pdf_bytes = await page.pdf(
                format="A4",
                margin={
                    "top": "25mm",
                    "bottom": "25mm",
                    "left": "20mm",
                    "right": "20mm",
                },
                print_background=True,
                prefer_css_page_size=True,
            )
        finally:
            await page.close()
    finally:
        await context.close()
    return pdf_bytes
