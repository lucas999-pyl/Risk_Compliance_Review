from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.factory import create_app
from app.settings import Settings


SDS_TEXT = """
1. Identification
Product name: Demo Solvent Blend
Recommended use: Industrial cleaning solvent
Supplier: Demo Chemicals Ltd.

2. Hazard identification
GHS classification: Flammable liquid Category 2; Eye irritation Category 2
Hazard statements: H225 Highly flammable liquid and vapour. H319 Causes serious eye irritation.
Precautionary statements: P210 Keep away from heat.

3. Composition/information on ingredients
Ethanol CAS 64-17-5 EC 200-578-6 60%
Acetone CAS 67-64-1 EC 200-662-2 40%

4. First-aid measures
Move person to fresh air.
5. Fire-fighting measures
Use alcohol-resistant foam.
6. Accidental release measures
Avoid ignition sources.
7. Handling and storage
Store in a cool place.
8. Exposure controls/personal protection
Use eye protection.
9. Physical and chemical properties
Flash point: 12 C
10. Stability and reactivity
Stable under normal conditions.
11. Toxicological information
May cause eye irritation.
12. Ecological information
No data available.
13. Disposal considerations
Dispose according to local rules.
14. Transport information
UN 1993 Flammable liquid, n.o.s.
15. Regulatory information
See applicable chemical regulations.
16. Other information
Revision date: 2026-05-01
"""


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        database_path=str(tmp_path / "risk-review.db"),
        storage_dir=str(tmp_path / "objects"),
        enable_llm=False,
    )
    return TestClient(create_app(settings))


def create_case(client: TestClient) -> str:
    response = client.post(
        "/cases",
        json={
            "title": "Demo solvent pre-review",
            "material_type": "mixture",
            "target_markets": ["CN", "EU", "US"],
            "intended_use": "industrial cleaning solvent",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def upload_sds(client: TestClient, case_id: str) -> str:
    response = client.post(
        f"/cases/{case_id}/documents",
        data={"document_type": "sds", "source_name": "supplier"},
        files={"file": ("demo-sds.txt", SDS_TEXT.encode("utf-8"), "text/plain")},
    )
    assert response.status_code == 201
    return response.json()["id"]


def seed_regulatory_knowledge(client: TestClient) -> list[str]:
    source_payloads = [
        {
            "title": "China hazardous chemicals demo extract",
            "jurisdiction": "CN",
            "source_type": "official_law",
            "source_url": "https://www.npc.gov.cn/npc/c2/c30834/202512/t20251227_450713.html",
            "version": "2026-05-01",
            "effective_date": "2026-05-01",
            "license_note": "Customer-provided or official public metadata only.",
        },
        {
            "title": "EU REACH/SVHC demo extract",
            "jurisdiction": "EU",
            "source_type": "official_registry",
            "source_url": "https://www.echa.europa.eu/candidate-list-table",
            "version": "2026-01",
            "effective_date": "2026-01-01",
            "license_note": "Public registry metadata.",
        },
        {
            "title": "US TSCA/HCS demo extract",
            "jurisdiction": "US",
            "source_type": "official_registry",
            "source_url": "https://www.epa.gov/tsca-inventory",
            "version": "2026-01",
            "effective_date": "2026-01-01",
            "license_note": "Public registry metadata.",
        },
    ]
    source_ids: list[str] = []
    for payload in source_payloads:
        response = client.post("/knowledge/sources", json=payload)
        assert response.status_code == 201
        source_ids.append(response.json()["id"])

    ingest_payloads = [
        {
            "source_id": source_ids[0],
            "content": "Ethanol CAS 64-17-5 and acetone CAS 67-64-1 are handled as hazardous chemical evidence in this demo rule pack.",
        },
        {
            "source_id": source_ids[1],
            "content": "Ethanol CAS 64-17-5 and acetone CAS 67-64-1 are not demo SVHC matches; absence of a match still requires source-backed reporting.",
        },
        {
            "source_id": source_ids[2],
            "content": "TSCA Inventory demo extract: ethanol CAS 64-17-5 active; acetone CAS 67-64-1 active. OSHA HCS requires SDS hazard communication.",
        },
    ]
    for payload in ingest_payloads:
        response = client.post("/knowledge/ingest", json=payload)
        assert response.status_code == 201
        assert response.json()["chunk_count"] >= 1
    return source_ids


def test_review_without_regulatory_evidence_is_conservative(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    case_id = create_case(client)
    upload_sds(client, case_id)

    run_response = client.post(f"/cases/{case_id}/run-review")
    assert run_response.status_code == 202

    findings = client.get(f"/cases/{case_id}/findings").json()
    assert findings
    assert all(finding["requires_human_review"] for finding in findings)
    assert any(finding["issue_type"] == "insufficient_regulatory_evidence" for finding in findings)
    assert all(finding["evidence_ids"] for finding in findings)


def test_review_with_knowledge_produces_structured_source_backed_findings(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    case_id = create_case(client)
    document_id = upload_sds(client, case_id)
    source_ids = seed_regulatory_knowledge(client)

    run_response = client.post(f"/cases/{case_id}/run-review")
    assert run_response.status_code == 202
    assert run_response.json()["status"] == "completed"

    findings = client.get(f"/cases/{case_id}/findings").json()
    assert {finding["jurisdiction"] for finding in findings} >= {"CN", "EU", "US"}
    assert any(finding["issue_type"] == "regulated_substance_match" for finding in findings)
    assert any(finding["issue_type"] == "tsca_inventory_match" for finding in findings)
    assert all(finding["conclusion"] for finding in findings)
    assert all(finding["evidence_ids"] for finding in findings)
    assert all(finding["regulation_refs"] for finding in findings)
    assert any(document_id in finding["evidence_ids"] for finding in findings)
    assert any(
        any(evidence_id.startswith("chunk_") for evidence_id in finding["evidence_ids"])
        for finding in findings
    )
    assert source_ids


def test_human_review_decision_is_audited_and_reported(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    case_id = create_case(client)
    upload_sds(client, case_id)
    seed_regulatory_knowledge(client)
    client.post(f"/cases/{case_id}/run-review")
    finding_id = client.get(f"/cases/{case_id}/findings").json()[0]["id"]

    review_response = client.post(
        f"/findings/{finding_id}/review",
        json={
            "decision": "approved",
            "reviewer": "ehs.specialist@example.com",
            "comment": "Evidence and conservative conclusion accepted for pre-review.",
        },
    )
    assert review_response.status_code == 201
    assert review_response.json()["audit_log_id"].startswith("audit_")

    report_response = client.get(f"/cases/{case_id}/report")
    assert report_response.status_code == 200
    report = report_response.json()
    assert report["case"]["id"] == case_id
    assert report["summary"]["reviewed_findings"] >= 1
    assert any(
        finding["review_status"] == "approved" and finding["reviewer"] == "ehs.specialist@example.com"
        for finding in report["findings"]
    )
