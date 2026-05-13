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
import os
import re
import shutil
import subprocess
import tempfile
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.store import SQLiteStore


def _system_chromium_executable() -> str | None:
    candidates = [
        os.environ.get("RCR_CHROMIUM_PATH"),
        shutil.which("msedge"),
        shutil.which("chrome"),
        shutil.which("chromium"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    return None


class PDFRendererUnavailable(RuntimeError):
    """Playwright / chromium 不可用（未装、driver 损坏、启动失败等）。"""


class CaseNotReady(RuntimeError):
    """Case 未完成预审或 latest_report 缺失。"""


# verdict_zh 映射 —— 严格按 HANDOFF §4
_VERDICT_ZH = {
    "pass": "可审",
    "needs_review": "需复核",
    "needs_supplement": "待补",
    "not_approved": "不建议准入",
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
    "not_approved": "不建议准入",
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
    "sds": "安全技术说明书",
    "formula": "配方 / 成分明细",
    "process": "工艺说明",
    "process_flow": "工艺说明",
    "test_report": "检测报告",
    "label": "标签",
    "certificate": "资质证明",
    "supplier": "供应商资料",
    "document": "文档",
}

_RULE_NAME_ZH = {
    "document_completeness_precheck": "资料完整性预检",
    "formula_components_missing": "配方组分缺失核查",
    "package_precheck": "资料包预检",
    "knowledge_pack_missing_review": "规则库资料缺失复核",
    "knowledge_no_match_review": "法规知识未命中复核",
    "sds_missing_sections": "安全技术说明书关键章节缺失核查",
    "sds_key_sections": "安全技术说明书关键章节核查",
    "tsca_inventory_match": "美国化学品清单状态核查",
    "hazardous_catalog_match": "危险化学品目录命中核查",
    "ghs_label_pictogram_missing": "化学品分类标签与象形图核查",
    "sds_section_completeness": "安全技术说明书章节完整性核查",
    "incompatibility_oxidizer_flammable": "可燃液体与氧化剂禁忌组合",
    "incompatibility_hypochlorite_acid": "次氯酸盐与酸类禁忌组合",
    "source_backed_no_restricted_demo_match": "禁限用物质证据化筛查",
    "svhc_threshold_match": "欧盟高度关注物质阈值核查",
    "voc_limit_exceeded": "挥发性有机物限值合规核查",
    "formula_cas_missing": "配方组分登记号完整性核查",
    "process_parameters_missing": "工艺关键参数完整性核查",
    "flammable_storage_missing": "可燃液体储存条件核查",
    "enterprise_redline_benzene": "企业红线禁苯核查",
    "transport_un_mismatch": "运输编号与危险类别一致性核查",
    "sds_revision_outdated": "安全技术说明书修订日期时效核查",
    "oxidizer_high_temperature_process": "氧化剂高温工艺安全核查",
    "unknown_substance_review": "未知 / 未命中物质复核",
    "manual_review": "人工复核",
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
            executable_path = _system_chromium_executable()
            _browser = await _playwright_ctx.chromium.launch(
                executable_path=executable_path,
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
    labels = {
        "CN": "中国",
        "EU": "欧盟",
        "US": "美国",
        "KR": "韩国",
        "JP": "日本",
    }
    return " / ".join(labels.get(str(item), str(item)) for item in markets)


def _scenario_label(scenario: str | None) -> str:
    if not scenario:
        return "—"
    return _SCENARIO_LABELS.get(scenario, scenario)


def _verdict_summary(customer_report: dict[str, Any]) -> str:
    summary = customer_report.get("summary") or customer_report.get("executive_summary") or ""
    if isinstance(summary, list):
        summary = "；".join(str(item) for item in summary if item)
    return _localize_rule_text(str(summary or "").strip()) or "本案已完成预审，详见以下各章节。"


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


def _rule_name(rule_id: str | None) -> str:
    if not rule_id:
        return "—"
    value = str(rule_id)
    return _RULE_NAME_ZH.get(value, value)


def _localize_rule_text(text: str | None) -> str:
    out = str(text or "")
    for rule_id, name in _RULE_NAME_ZH.items():
        out = out.replace(f"规则 {rule_id}", f"规则 {name}")
        out = out.replace(f"命中规则 {rule_id}", f"命中{name}")
        out = out.replace(rule_id, name)
    replacements = [
        (r"\bREACH/SVHC\b", "欧盟化学品法规/高度关注物质"),
        (r"\bTSCA/HCS\b", "美国化学品清单/危害沟通标准"),
        (r"\bTSCA\b", "美国化学品清单"),
        (r"\bGHS\b", "全球统一分类和标签制度"),
        (r"\bSDS\b", "安全技术说明书"),
        (r"\bMSDS\b", "安全技术说明书"),
        (r"\bVOC\b", "挥发性有机物"),
        (r"\bCAS\b", "化学文摘登记号"),
        (r"\bSVHC\b", "高度关注物质"),
        (r"\bREACH\b", "欧盟化学品法规"),
        (r"\bHCS\b", "危害沟通标准"),
        (r"\bEHS\b", "环境健康安全"),
        (r"\bUN\s*编号\b", "运输编号"),
        (r"\bUN\b", "运输编号"),
    ]
    for pattern, replacement in replacements:
        out = re.sub(pattern, replacement, out)
    return out


def _quote_parts_html(text: str | None) -> str:
    localized = _localize_rule_text(text)
    markers = [
        "执行要求：",
        "补充说明：",
    ]
    indexes = [localized.find(marker) for marker in markers if localized.find(marker) >= 0]
    if not indexes:
        return f'<span class="quote">{_esc(localized)}</span>'
    idx = min(indexes)
    main = localized[:idx].strip()
    supplement = localized[idx:].strip()
    parts = []
    if main:
        parts.append(_esc(main))
    if supplement:
        parts.append(f'<span class="quote-supplement">{_esc(supplement)}</span>')
    return f'<span class="quote">{"".join(parts)}</span>'


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
        raw_rule_title = item.get("rule_name_zh") or (item.get("rule") or {}).get("name_zh") or rule_id
        rule_title = _localize_rule_text(_rule_name(raw_rule_title))
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
        rule_block = f'<span class="rid">{_esc(rule_title)}</span>'
        rule_quote = _quote_parts_html(rule_text) if rule_text else ""
        user_block = (
            _quote_parts_html(user_text)
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


def render_case_report_pdf_with_system_browser(case: dict[str, Any], payload: dict[str, Any], documents: list[dict[str, Any]] | None = None) -> bytes:
    executable = _system_chromium_executable()
    if not executable:
        raise PDFRendererUnavailable("系统未找到 Chrome/Edge 可执行文件")
    html_text = build_print_html(case, payload, documents=documents)
    with tempfile.TemporaryDirectory(prefix="rcr_pdf_") as tmp:
        tmp_path = Path(tmp)
        html_path = tmp_path / "report.html"
        pdf_path = tmp_path / "report.pdf"
        profile_path = tmp_path / "profile"
        html_path.write_text(html_text, encoding="utf-8")
        cmd = [
            executable,
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            f"--user-data-dir={profile_path}",
            f"--print-to-pdf={pdf_path}",
            str(html_path),
        ]
        result = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, timeout=60)
        if result.returncode != 0 or not pdf_path.exists():
            raise PDFRendererUnavailable((result.stderr or result.stdout or "系统浏览器 PDF 导出失败").strip())
        return pdf_path.read_bytes()


def build_fallback_pdf(case: dict[str, Any], payload: dict[str, Any]) -> bytes:
    """Built-in PDF fallback for machines without Playwright/Chromium."""
    customer_report = payload.get("customer_report") or {}
    verdict = customer_report.get("verdict") or payload.get("verdict") or "review"
    summary = _localize_rule_text(customer_report.get("summary") or "审查报告已生成。")
    title = case.get("title") or case.get("id") or "Risk Compliance Review"
    issue_groups = customer_report.get("issue_groups") or []
    lines = [
        "化工合规 RAG 预审 - 审查报告",
        f"Case ID: {case.get('id', '')}",
        f"案件标题: {title}",
        f"目标市场: {_target_market_text(case.get('target_markets'))}",
        f"审查结论: {_VERDICT_ZH.get(str(verdict), str(verdict))}",
        "",
        "摘要",
        str(summary),
        "",
        "不合规 / 复核事项",
    ]
    if not issue_groups:
        lines.append("本次审查未发现需要客户立即处理的不合格或复核事项。")
    for group in issue_groups:
        group_title = group.get("title") or group.get("group") or "问题组"
        lines.append(f"- {group_title}")
        for item in group.get("items") or []:
            name = _rule_name(item.get("rule_name_zh") or item.get("rule_id") or item.get("id") or "事项")
            recommendation = item.get("recommendation") or ""
            user_text = item.get("user_text") or ""
            lines.append(f"  * {name}")
            if user_text:
                lines.append(f"    用户原文: {user_text}")
            if recommendation:
                lines.append(f"    建议: {recommendation}")
    lines.append("")
    lines.append("注：当前机器未安装 Chromium，已使用内置 PDF 渲染；网页报告内容保持一致。")

    def pdf_text(value: Any) -> str:
        text = str(value).encode("latin-1", "replace").decode("latin-1")
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    content_parts = ["BT", "/F1 12 Tf", "72 790 Td"]
    first = True
    wrapped_lines: list[str] = []
    for line in lines:
      text = str(line)
      while len(text) > 84:
          wrapped_lines.append(text[:84])
          text = text[84:]
      wrapped_lines.append(text)
    for line in wrapped_lines[:38]:
        if first:
            first = False
        else:
            content_parts.append("0 -18 Td")
        content_parts.append(f"({pdf_text(line)}) Tj")
    content_parts.append("ET")
    stream = "\n".join(content_parts).encode("latin-1")
    compressed = zlib.compress(stream)

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(compressed) + compressed + b"\nendstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{idx} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    return bytes(pdf)


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
