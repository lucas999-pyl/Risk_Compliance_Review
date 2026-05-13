from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from typing import Literal


ParseStatus = Literal["parsed", "needs_manual_review", "parse_failed"]

SECTION_PATTERN = re.compile(
    r"(?m)^\s*(?:#+\s*)?"
    r"(?:第\s*)?"
    r"(?P<number>1[0-6]|[1-9])"
    r"(?:\s*章)?"
    r"[\.\)：:]?\s+"
    r"(?P<title>\S[^\n\r]*?)\s*$"
)
MD_TABLE_LINE = re.compile(r"^\s*\|.+\|\s*$")
MD_TABLE_SEPARATOR = re.compile(r"^\s*-+\s*$|^\s*:?-+:?\s*$")
CAS_PATTERN = re.compile(r"\b(?P<cas>\d{2,7}-\d{2}-\d)\b")
COMPONENT_PATTERN = re.compile(
    r"(?m)^\s*(?P<name>.+?)\s+CAS\s+"
    r"(?P<cas>\d{2,7}-\d{2}-\d)"
    r"(?:\s+EC\s+(?P<ec>[0-9-]+|not assigned|未分配|不适用|N/?A))?"
    r"\s+(?P<concentration>\d+(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)
HAZARD_PATTERN = re.compile(r"\bH\d{3}[A-Z]?\b")
PRECAUTION_PATTERN = re.compile(r"\bP\d{3}[A-Z]?\b")
UN_PATTERN = re.compile(r"\bUN\s*(?P<un>\d{4})\b", re.IGNORECASE)
SUPPLIER_PATTERN = re.compile(r"(?im)^\s*(?:供应商|Supplier)\s*[:：]\s*(?P<value>.+?)\s*$")
PRODUCT_PATTERN = re.compile(r"(?im)^\s*(?:产品名称|Product name)\s*[:：]\s*(?P<value>.+?)\s*$")
REVISION_PATTERN = re.compile(r"(?im)^\s*(?:修订日期|Revision date)\s*[:：]\s*(?P<value>.+?)\s*$")


@dataclass(frozen=True)
class ExtractedSection:
    number: int
    title: str
    content: str


@dataclass(frozen=True)
class ExtractedComponent:
    name: str
    cas: str
    ec: str | None
    concentration_text: str
    concentration_min: float
    concentration_max: float


@dataclass(frozen=True)
class ParsedDocument:
    sections: list[ExtractedSection]
    components: list[ExtractedComponent]
    metadata: dict[str, object]
    extracted_fields: dict[str, object]
    missing_fields: list[str]
    parse_status: ParseStatus
    needs_manual_review: bool
    text_source: str = "text"


def extract_text_from_bytes(raw: bytes, *, filename: str | None = None, content_type: str | None = None) -> tuple[str, str]:
    is_pdf = (content_type or "").lower() == "application/pdf" or (filename or "").lower().endswith(".pdf")
    if is_pdf:
        text = _extract_pdf_text(raw)
        return text, "pdf_text" if text.strip() else "pdf_unreadable"
    return raw.decode("utf-8", errors="ignore"), "text"


def parse_document_bytes(raw: bytes, *, filename: str | None = None, content_type: str | None = None) -> ParsedDocument:
    text, text_source = extract_text_from_bytes(raw, filename=filename, content_type=content_type)
    if text_source == "pdf_unreadable":
        return ParsedDocument(
            sections=[],
            components=[],
            metadata={
                "cas_numbers": [],
                "hazard_statements": [],
                "precautionary_statements": [],
                "un_numbers": [],
                "sds_section_numbers": [],
            },
            extracted_fields={},
            missing_fields=["machine_readable_text"],
            parse_status="parse_failed",
            needs_manual_review=True,
            text_source="pdf_unreadable",
        )
    return parse_document_text(text, text_source=text_source)


def parse_document_text(text: str, text_source: str = "text") -> ParsedDocument:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    sections = extract_sds_sections(normalized)
    components = extract_components(normalized)
    sds_section_numbers = [section.number for section in sections]
    metadata = {
        "cas_numbers": sorted(set(CAS_PATTERN.findall(normalized))),
        "hazard_statements": sorted(set(HAZARD_PATTERN.findall(normalized))),
        "precautionary_statements": sorted(set(PRECAUTION_PATTERN.findall(normalized))),
        "un_numbers": sorted(set(match.group("un") for match in UN_PATTERN.finditer(normalized))),
        "sds_section_numbers": sds_section_numbers,
    }
    extracted_fields = {
        "product_name": _first_match(PRODUCT_PATTERN, normalized),
        "supplier": _first_match(SUPPLIER_PATTERN, normalized),
        "revision_date": _first_match(REVISION_PATTERN, normalized),
        "cas_numbers": metadata["cas_numbers"],
        "hazard_statements": metadata["hazard_statements"],
        "precautionary_statements": metadata["precautionary_statements"],
        "un_numbers": metadata["un_numbers"],
        "sds_section_numbers": sds_section_numbers,
        "component_count": len(components),
    }
    missing_fields = validate_extracted_fields(extracted_fields, sections, components)
    return ParsedDocument(
        sections=sections,
        components=components,
        metadata=metadata,
        extracted_fields=extracted_fields,
        missing_fields=missing_fields,
        parse_status="needs_manual_review" if missing_fields else "parsed",
        needs_manual_review=bool(missing_fields),
        text_source=text_source,
    )


def validate_extracted_fields(
    extracted_fields: dict[str, object],
    sections: list[ExtractedSection],
    components: list[ExtractedComponent],
) -> list[str]:
    missing: list[str] = []
    section_numbers = {section.number for section in sections}
    if section_numbers != set(range(1, 17)):
        missing.append("sds_sections")
    if not extracted_fields.get("supplier"):
        missing.append("supplier")
    if not components:
        missing.append("cas_numbers")
        missing.append("component_concentrations")
    elif any(component.concentration_min is None or component.concentration_max is None for component in components):
        missing.append("component_concentrations")
    if not extracted_fields.get("revision_date") and section_numbers == set(range(1, 17)):
        missing.append("revision_date")
    return missing


def extract_sds_sections(text: str) -> list[ExtractedSection]:
    matches = list(SECTION_PATTERN.finditer(text))
    sections: list[ExtractedSection] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append(
            ExtractedSection(
                number=int(match.group("number")),
                title=match.group("title").strip(),
                content=text[start:end].strip(),
            )
        )
    return sections


def extract_components(text: str) -> list[ExtractedComponent]:
    components: list[ExtractedComponent] = []
    for match in COMPONENT_PATTERN.finditer(text):
        concentration = float(match.group("concentration"))
        ec = match.group("ec")
        if ec and not re.fullmatch(r"[0-9-]+", ec):
            ec = None
        components.append(
            ExtractedComponent(
                name=match.group("name").strip(" :-"),
                cas=match.group("cas"),
                ec=ec,
                concentration_text=f"{match.group('concentration')}%",
                concentration_min=concentration,
                concentration_max=concentration,
            )
        )
    if not components:
        components = list(extract_components_from_markdown_table(text))
    return components


def extract_components_from_markdown_table(text: str) -> list[ExtractedComponent]:
    results: list[ExtractedComponent] = []
    headers: list[str] = []
    col: dict[str, int] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not MD_TABLE_LINE.match(line):
            headers = []
            col = {}
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells and all((not c) or MD_TABLE_SEPARATOR.match(c) for c in cells):
            continue
        if not headers:
            headers = cells
            for i, h in enumerate(cells):
                hl = h.lower().replace(" ", "")
                if "cas" in hl and "cas" not in col:
                    col["cas"] = i
                elif (hl == "ec" or "ec号" in hl or "ec编号" in hl) and "ec" not in col:
                    col["ec"] = i
                elif ("含量" in h or "浓度" in h or "%" in h or "比例" in h or "wt" in hl) and "conc" not in col:
                    col["conc"] = i
                elif ("中文名" in h or "组分" in h or "名称" in h) and "name" not in col:
                    col["name"] = i
            continue
        if "cas" not in col or len(cells) <= col["cas"]:
            continue
        cas_m = re.search(r"\b(\d{2,7}-\d{2}-\d)\b", cells[col["cas"]])
        if not cas_m:
            continue
        cas = cas_m.group(1)
        name = cells[col["name"]].strip(" :-") if "name" in col and len(cells) > col["name"] else cas
        if not name or "合计" in name or "总计" in name:
            continue
        conc_min = 0.0
        conc_max = 0.0
        conc_text = ""
        if "conc" in col and len(cells) > col["conc"]:
            cell = cells[col["conc"]]
            cm = re.search(r"(\d+(?:\.\d+)?)(?:\s*[-~–]\s*(\d+(?:\.\d+)?))?", cell)
            if cm:
                conc_min = float(cm.group(1))
                conc_max = float(cm.group(2)) if cm.group(2) else conc_min
                conc_text = f"{cell}%" if "%" not in cell else cell
        ec = None
        if "ec" in col and len(cells) > col["ec"]:
            ev = cells[col["ec"]]
            if re.fullmatch(r"[0-9-]+", ev):
                ec = ev
        results.append(
            ExtractedComponent(
                name=name,
                cas=cas,
                ec=ec,
                concentration_text=conc_text,
                concentration_min=conc_min,
                concentration_max=conc_max,
            )
        )
    return results


def _extract_pdf_text(raw: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(raw))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return _extract_simple_pdf_literal_text(raw)


def _extract_simple_pdf_literal_text(raw: bytes) -> str:
    decoded = raw.decode("latin-1", errors="ignore")
    literals = re.findall(r"\((.*?)\)\s*Tj", decoded, flags=re.DOTALL)
    text = "\n".join(literals)
    return (
        text.replace(r"\n", "\n")
        .replace(r"\(", "(")
        .replace(r"\)", ")")
        .replace(r"\\", "\\")
    )


def _first_match(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    return match.group("value").strip()
