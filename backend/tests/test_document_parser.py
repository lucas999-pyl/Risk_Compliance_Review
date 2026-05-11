from __future__ import annotations

from app.document_parser import parse_document_bytes, parse_document_text


def test_parse_chinese_sds_sections_and_components() -> None:
    text = """
1. 化学品及企业标识
产品名称：中文测试溶剂
供应商：演示化学品有限公司
2. 危险性概述
危险性说明：H225 高度易燃液体和蒸气。
防范说明：P210 远离热源。
3. 成分/组成信息
乙醇 CAS 64-17-5 EC 200-578-6 60%
丙酮 CAS 67-64-1 EC 200-662-2 40%

4. 急救措施
移至空气新鲜处。
5. 消防措施
使用泡沫灭火。
6. 泄漏应急处理
避免进入下水道。
7. 操作处置与储存
储存在阴凉处。
8. 接触控制和个体防护
佩戴防护眼镜。
9. 理化特性
闪点：12 C
10. 稳定性和反应性
正常条件下稳定。
11. 毒理学信息
可能造成眼刺激。
12. 生态学信息
无数据。
13. 废弃处置
按当地法规处置。
14. 运输信息
UN 1993 易燃液体。
15. 法规信息
见适用法规。
16. 其他信息
修订日期：2026-05-01
"""

    parsed = parse_document_text(text)

    assert [section.number for section in parsed.sections] == list(range(1, 17))
    assert parsed.parse_status == "parsed"
    assert parsed.metadata["hazard_statements"] == ["H225"]
    assert parsed.metadata["precautionary_statements"] == ["P210"]
    assert parsed.extracted_fields["supplier"] == "演示化学品有限公司"
    assert [component.name for component in parsed.components] == ["乙醇", "丙酮"]
    assert [component.cas for component in parsed.components] == ["64-17-5", "67-64-1"]


def test_validation_marks_incomplete_sds_for_manual_review() -> None:
    parsed = parse_document_text(
        """
1. 化学品及企业标识
产品名称：保密添加剂
供应商：供应商 A
3. 成分/组成信息
专有添加剂 商业秘密 35%
"""
    )

    assert parsed.parse_status == "needs_manual_review"
    assert parsed.needs_manual_review is True
    assert "sds_sections" in parsed.missing_fields
    assert "cas_numbers" in parsed.missing_fields
    assert "component_concentrations" in parsed.missing_fields


def test_parse_text_pdf_extracts_sds_content() -> None:
    pdf_bytes = _minimal_pdf_bytes(
        """
1. Identification
Product name: PDF Solvent
Supplier: PDF Chemicals Ltd.
2. Hazard identification
Hazard statements: H225 Highly flammable liquid and vapour.
3. Composition/information on ingredients
Ethanol CAS 64-17-5 EC 200-578-6 60%
4. First-aid measures
Move person to fresh air.
"""
    )

    parsed = parse_document_bytes(pdf_bytes, filename="sds.pdf", content_type="application/pdf")

    assert parsed.parse_status == "needs_manual_review"
    assert parsed.text_source == "pdf_text"
    assert parsed.extracted_fields["supplier"] == "PDF Chemicals Ltd."
    assert [component.cas for component in parsed.components] == ["64-17-5"]
    assert "sds_sections" in parsed.missing_fields


def test_parse_scanned_or_unreadable_pdf_returns_conservative_failure() -> None:
    parsed = parse_document_bytes(
        b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF",
        filename="scan.pdf",
        content_type="application/pdf",
    )

    assert parsed.parse_status == "parse_failed"
    assert parsed.needs_manual_review is True
    assert parsed.text_source == "pdf_unreadable"
    assert "machine_readable_text" in parsed.missing_fields


def _minimal_pdf_bytes(text: str) -> bytes:
    escaped = (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\r", "")
        .replace("\n", "\\n")
    )
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("utf-8")
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        b"5 0 obj << /Length " + str(len(stream)).encode("ascii") + b" >> stream\n" + stream + b"\nendstream endobj\n",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(output))
        output.extend(obj)
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)
