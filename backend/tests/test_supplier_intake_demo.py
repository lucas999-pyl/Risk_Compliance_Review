from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.factory import create_app
from app.settings import Settings


SDS_TEXT = """
1. 化学品及企业标识
产品名称：演示溶剂混合物
推荐用途：金属部件工业清洗溶剂
供应商：演示化学品有限公司
2. 危险性概述
GHS 分类：易燃液体 类别 2；眼刺激 类别 2
危险性说明：H225 高度易燃液体和蒸气。H319 造成严重眼刺激。
防范说明：P210 远离热源。P280 戴防护手套和眼部防护。
3. 成分/组成信息
乙醇 CAS 64-17-5 EC 200-578-6 60%
丙酮 CAS 67-64-1 EC 200-662-2 40%

4. 急救措施
移至空气新鲜处。
5. 消防措施
使用抗醇泡沫。
6. 泄漏应急处理
移除火源并加强通风。
7. 操作处置与储存
储存在阴凉通风处。
8. 接触控制和个体防护
使用眼部防护。
9. 理化特性
闪点：12 C
10. 稳定性和反应性
正常条件下稳定。
11. 毒理学信息
可能引起眼刺激。
12. 生态学信息
无数据。
13. 废弃处置
按当地规则处置。
14. 运输信息
UN 1993 易燃液体，未另列明。
15. 法规信息
见适用化学品法规。
16. 其他信息
修订日期：2026-05-01
"""


def test_supplier_intake_upload_exposes_parse_validation_and_report_structure(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _seed_demo_regulatory_pack(client)

    created_case = client.post(
        "/cases",
        json={
            "title": "供应商演示溶剂准入",
            "material_type": "mixture",
            "target_markets": ["CN", "EU", "US"],
            "intended_use": "供应商物料准入",
        },
    )
    assert created_case.status_code == 201
    case_id = created_case.json()["id"]

    uploaded = client.post(
        f"/cases/{case_id}/documents",
        data={"document_type": "sds", "source_name": "supplier"},
        files={"file": ("supplier-sds.txt", SDS_TEXT.encode("utf-8"), "text/plain")},
    )

    assert uploaded.status_code == 201
    document = uploaded.json()
    assert document["parse_status"] == "parsed"
    assert document["needs_manual_review"] is False
    assert document["extracted_fields"]["supplier"] == "演示化学品有限公司"
    assert document["extracted_fields"]["sds_section_numbers"] == list(range(1, 17))
    assert document["missing_fields"] == []

    run = client.post(f"/cases/{case_id}/run-review")
    assert run.status_code == 202

    findings = client.get(f"/cases/{case_id}/findings").json()
    assert findings
    assert all(finding["evidence_ids"] for finding in findings)
    assert all(finding["recommended_action"] for finding in findings)
    source_backed = [finding for finding in findings if finding["jurisdiction"] in {"CN", "EU", "US"}]
    assert source_backed
    assert all(any(ref.startswith(f"{finding['jurisdiction']}:") for ref in finding["regulation_refs"]) for finding in source_backed)
    assert any("https://" in ref for finding in source_backed for ref in finding["regulation_refs"])

    report_response = client.get(f"/cases/{case_id}/report")
    assert report_response.status_code == 200
    report = report_response.json()
    assert report["report_type"] == "supplier_material_intake_pre_review"
    assert "AI 辅助预审" in report["disclaimer"]
    assert report["document_readiness"]["documents"][0]["parse_status"] == "parsed"
    assert report["composition"]["components"][0]["cas"] == "64-17-5"
    assert report["jurisdiction_risks"]
    assert report["supplier_follow_up_actions"]


def test_extraction_field_review_is_audited(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    created_case = client.post(
        "/cases",
        json={
            "title": "字段复核案件",
            "material_type": "mixture",
            "target_markets": ["CN"],
            "intended_use": "供应商准入",
        },
    )
    case_id = created_case.json()["id"]
    uploaded = client.post(
        f"/cases/{case_id}/documents",
        data={"document_type": "sds", "source_name": "supplier"},
        files={"file": ("supplier-sds.txt", SDS_TEXT.encode("utf-8"), "text/plain")},
    )
    document_id = uploaded.json()["id"]

    response = client.post(
        f"/documents/{document_id}/extraction-review",
        json={
            "reviewer": "ehs@example.com",
            "decision": "edited",
            "comment": "供应商名称按盖章文件修正。",
            "edited_fields": {"supplier": "演示化学品股份有限公司"},
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["audit_log_id"].startswith("audit_")
    assert payload["edited_fields"]["supplier"] == "演示化学品股份有限公司"


def _make_client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                database_path=str(tmp_path / "risk-review.db"),
                storage_dir=str(tmp_path / "objects"),
                enable_llm=False,
            )
        )
    )


def _seed_demo_regulatory_pack(client: TestClient) -> None:
    pack = {
        "sources": [
            {
                "title": "中国危险化学品目录演示摘录",
                "jurisdiction": "CN",
                "source_type": "official_law",
                "source_url": "https://www.mem.gov.cn/gk/gwgg/agwzlfl/gfxwj/2015/201509/t20150902_242909.shtml",
                "version": "2015-demo",
                "effective_date": "2015-09-02",
                "license_note": "演示数据，生产环境需导入授权来源。",
                "content": "演示中国来源支持筛查数据：乙醇 CAS 64-17-5 和丙酮 CAS 67-64-1 在本演示包中按危险化学品命中处理。",
            },
            {
                "title": "欧盟 REACH/SVHC 演示摘录",
                "jurisdiction": "EU",
                "source_type": "official_registry",
                "source_url": "https://www.echa.europa.eu/en/candidate-list-table",
                "version": "2026-01-demo",
                "effective_date": "2026-01-01",
                "license_note": "演示数据，生产环境需导入当前 ECHA 数据。",
                "content": "演示欧盟来源支持筛查数据：双酚A CAS 80-05-7 按候选清单 SVHC 命中处理；乙醇 CAS 64-17-5 和丙酮 CAS 67-64-1 为未命中对照。",
            },
            {
                "title": "美国 TSCA/HCS 演示摘录",
                "jurisdiction": "US",
                "source_type": "official_registry",
                "source_url": "https://www.epa.gov/tsca-inventory",
                "version": "2026-01-demo",
                "effective_date": "2026-01-01",
                "license_note": "演示数据，生产环境需导入授权 EPA/OSHA 来源。",
                "content": "演示美国来源支持筛查数据：乙醇 CAS 64-17-5 和丙酮 CAS 67-64-1 在本演示 TSCA 清单摘录中为 active。",
            },
        ]
    }
    for source in pack["sources"]:
        content = source["content"]
        created = client.post("/knowledge/sources", json={key: value for key, value in source.items() if key != "content"})
        assert created.status_code == 201, created.text
        ingested = client.post("/knowledge/ingest", json={"source_id": created.json()["id"], "content": content})
        assert ingested.status_code == 201, ingested.text
