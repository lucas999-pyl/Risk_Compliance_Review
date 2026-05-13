from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.factory import create_app
from app.settings import Settings


def test_static_workbench_is_served_with_upload_review_tabs(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            Settings(
                database_path=str(tmp_path / "risk-review.db"),
                storage_dir=str(tmp_path / "objects"),
                enable_llm=False,
            )
        )
    )

    response = client.get("/legacy")

    assert response.status_code == 200
    assert "化工合规 RAG 工具" in response.text
    assert "客户预审" in response.text
    assert "Case 流程" in response.text
    assert "创建 Case" in response.text
    assert "上传资料包" in response.text
    assert "资料包预检" in response.text
    assert "客户报告" in response.text
    assert "管理端" in response.text
    assert "向量检索实验" in response.text
    assert "RAG 链路" in response.text
    assert "TopK 原始召回" in response.text
    assert "Rerank 后排序" in response.text
    assert "清空知识库" in response.text
    assert "物料 Agent" in response.text
    assert "交叉质检" in response.text
    assert "供应商资料包" in response.text
    assert "供应商 B：含乙醇/过氧化氢清洗剂资料包" in response.text
    assert "/chemical/upload-review" in response.text
    assert "/chemical/evaluation" in response.text
    assert "/chemical/knowledge/status" in response.text
    assert "/chemical/knowledge/upload-pack" in response.text
    assert "/chemical/query-presets" in response.text
    assert "/chemical/knowledge/search" in response.text
    assert "技术流程 Demo" not in response.text
    assert "鍖栧" not in response.text


def test_customer_case_flow_is_primary_and_admin_debug_is_isolated() -> None:
    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "legacy.html").read_text(encoding="utf-8")

    assert 'id="customerWorkbench"' in html
    assert 'id="adminWorkbench"' in html
    assert 'data-mode="customer"' in html
    assert 'data-mode="admin"' in html
    assert "Case 流程" in html
    assert "1 创建 Case" in html
    assert "2 上传资料包" in html
    assert "3 资料包预检" in html
    assert "4 审查范围" in html
    assert "5 客户报告" in html
    assert 'id="createCase"' in html
    assert 'id="uploadCaseDocuments"' in html
    assert 'id="clearCases"' in html
    assert 'id="runCaseReview"' in html
    assert "选择资料包" in html
    assert "上传并预检" in html
    assert "不会运行正式审查" in html
    assert "保持新建表单" in html
    assert "function fillCaseFormFromCase" in html
    assert '$("uploadTitle").value = item.title' not in html
    assert "function renderCustomerFriendlyVerdict" in html
    assert "function customerFieldLabel" in html
    customer_html = html[html.index('id="customerWorkbench"') : html.index('id="adminWorkbench"')]
    assert "合规 / 复核 / 不合规" not in customer_html
    assert "规则：" not in customer_html
    assert "review_workbench.document_quality" not in customer_html
    assert "function ensureCaseReadyForReview" in html
    assert "await uploadCaseDocuments();" in html
    assert "await createCase();" in html
    assert 'api("/chemical/cases", { method: "DELETE" })' in html
    assert "/chemical/cases/${caseId}/documents" in html
    assert "/chemical/cases/${caseId}/run-review" in html
    assert "function setWorkbenchMode" in html
    assert "function updateCaseActionState" in html

    customer_start = html.index('id="customerWorkbench"')
    admin_start = html.index('id="adminWorkbench"')
    customer_html = html[customer_start:admin_start]
    assert "Trace JSON" not in customer_html
    assert "TopK 原始召回" not in customer_html
    assert "Agent 分支分析" not in customer_html
    assert 'id="reviewTask"' not in customer_html
    assert "Trace JSON" in html[admin_start:]
    assert "Agent 分支分析" in html[admin_start:]


def test_trace_node_click_selection_is_not_reset_on_rerender() -> None:
    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "legacy.html").read_text(encoding="utf-8")

    assert "function selectNode(nodeId)" in html
    assert "state.selectedNode = nodeId;" in html
    assert "const selectedNodeExists = trace.nodes.some((node) => node.node_id === state.selectedNode);" in html
    assert "if (!selectedNodeExists)" in html
    assert "trace.nodes.some((node) => node.node_id === state.selectedNode)" in html


def test_workbench_has_collapsible_result_sections_and_safe_text_wrapping() -> None:
    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "legacy.html").read_text(encoding="utf-8")

    assert 'class="collapse-toggle"' in html
    assert 'data-target="ragPipeline"' in html
    assert 'data-target="rawRecall"' in html
    assert 'data-target="rerankedChunks"' in html
    assert 'data-target="chunks"' in html
    assert "function toggleSection" in html
    assert ".detail-panel" in html
    assert ".collapsed" in html
    assert 'class="agent-grid collapsible"' in html
    assert 'class="graph collapsible"' in html
    assert "overflow-wrap: anywhere" in html
    assert "grid-template-columns: minmax(320px, 390px) minmax(0, 1fr) minmax(380px, 460px)" in html


def test_static_workbench_defaults_to_business_review_loop() -> None:
    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "legacy.html").read_text(encoding="utf-8")

    assert "原始资料" in html
    assert "抽取校验" in html
    assert "风险项" in html
    assert "证据链" in html
    assert "预审报告摘要" in html
    assert "技术细节" in html
    assert "sourceDocuments" in html
    assert "extractedChecklist" in html
    assert "riskItems" in html
    assert "reportSummary" in html
    assert "renderReviewWorkbench" in html
    assert 'data-target="technicalDetails"' in html
    assert "review_workbench" in html


def test_static_workbench_promotes_knowledge_base_and_upload_review() -> None:
    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "legacy.html").read_text(encoding="utf-8")

    assert "知识库工作台" in html
    assert "上传审查" in html
    assert "上传 SDS" in html
    assert "上传配方表" in html
    assert "上传工艺说明" in html
    assert "知识 Chunk" in html
    assert "向量检索实验" in html
    assert "Rerank 解释" in html
    assert "/chemical/upload-review" in html
    assert "/chemical/knowledge/chunks" in html
    assert "/chemical/knowledge/search" in html
    assert "上传官方知识库源文档" in html
    assert "本地可审计 demo 知识包" not in html
    assert "caseSelect" not in html
    assert "化工测试 Case" not in html
    assert "鍖栧伐" not in html
    assert "鐭ヨ瘑" not in html


def test_static_workbench_is_task_driven_upload_review() -> None:
    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "legacy.html").read_text(encoding="utf-8")

    assert "审查任务" in html
    assert "供应商资料包" in html
    assert "供应商 A：水性清洗剂准入资料包" in html
    assert "供应商 B：含乙醇/过氧化氢清洗剂资料包" in html
    assert "供应商 C：研发中间体资料缺口包" in html
    assert "任务拆解" in html
    assert "多 query RAG 召回" in html
    assert "Agent 分支分析" in html
    assert "主审汇总" in html
    assert 'id="reviewTask"' in html
    assert 'form.append("review_task", $("reviewTask").value);' in html
    assert "task_decomposition" in html
    assert "agent_branches" in html
    assert "chief_synthesis" in html
    assert "合规样张" not in html
    assert "不合规样张" not in html
    assert "复核样张" not in html


def test_static_workbench_uses_official_pack_and_business_query_workbench() -> None:
    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "legacy.html").read_text(encoding="utf-8")

    assert "上传官方知识库源文档" in html
    assert "manifest_file" in html
    assert "source_files" in html
    assert "/chemical/knowledge/upload-pack" in html
    assert "/chemical/query-presets" in html
    assert "任务推荐" in html
    assert "审查任务历史" in html
    assert "清空任务历史" in html
    assert "localStorage" in html
    assert "资料完整性与补件判断" in html
    assert "字段级清单" in html
    assert "document_quality" in html
    assert "supplement_actions" in html
    assert "导入本地可审计 demo 知识包" not in html
    assert "expected_verdict" not in html


def test_static_workbench_moves_presets_to_review_task_multi_select() -> None:
    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "legacy.html").read_text(encoding="utf-8")

    assert "任务推荐" in html
    assert "reviewTaskPresets" in html
    assert "selectedReviewTasks" in html
    assert "reviewTaskHistory" in html
    assert "clearReviewTaskHistory" in html
    assert "applySelectedReviewTasks" in html
    assert "chemicalRagReviewTaskHistory" in html
    assert "task-suggestions" in html
    assert "suggestion-chip" in html
    assert "可多选" in html
    assert "向量检索实验" in html
    assert "检索 Query" in html
    assert "高频问题" not in html
    assert "queryPresets" not in html
    assert "data_samples/chemical_knowledge_sources/official_pack_2026_05" in html
    assert "official_pack_2026_05.zip" in html


def test_static_workbench_explains_button_roles_and_empty_knowledge_state() -> None:
    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "legacy.html").read_text(encoding="utf-8")

    assert "主流程：1 上传官方知识库源文档" in html
    assert "内置评测集已收纳到开发者折叠区" in html
    assert "没有已上传的知识 Chunk" in html
    assert "知识库未加载，已阻止上传审查" in html
    assert "function renderEmptyKnowledgeChunks" in html
    assert "function setKnowledgeLoadedState" in html
    assert "知识库为空，检索实验不会返回固定内置结果" in html
    assert "运行内置评测集" in html


def test_static_workbench_locks_actions_while_uploading_knowledge_pack() -> None:
    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "legacy.html").read_text(encoding="utf-8")

    assert 'id="clearKnowledgeFiles"' in html
    assert "清除已选文件" in html
    assert "function clearKnowledgeFileInputs" in html
    assert "function setKnowledgeBusyState" in html
    assert "state.knowledgeBusy" in html
    assert "$(\"uploadKnowledgePack\").disabled = busy;" in html
    assert "$(\"loadChunks\").disabled = busy;" in html
    assert "$(\"clearKnowledge\").disabled = busy;" in html
    assert "$(\"runCaseReview\").disabled = busy || !state.knowledgeLoaded;" in html


def test_static_workbench_demotes_quality_evaluation_to_collapsed_developer_panel() -> None:
    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "legacy.html").read_text(encoding="utf-8")

    assert 'id="evalTab"' not in html
    assert 'id="traceTab"' not in html
    assert 'id="evalView"' not in html
    assert "质量评测（二级）" not in html
    assert "刷新质量评测（二级）" not in html
    assert "开发者质量评测 / 内置评测集" in html
    assert "运行内置评测集" in html
    assert "不参与现场上传审查" in html
    assert 'data-target="developerEvaluation"' in html
    assert 'id="developerEvaluation"' in html


def test_static_workbench_explains_source_documents_and_inline_flow_replay_detail() -> None:
    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "legacy.html").read_text(encoding="utf-8")

    assert "原始资料（上传文件原文 / 抽取依据）" in html
    assert "用于核对系统是否真实读取了 SDS、配方表和工艺说明" in html
    assert 'data-target="sourceDocumentsPanel"' in html
    assert 'id="sourceDocumentsPanel"' in html
    assert "点击节点可在下方查看该步骤输入输出" in html
    assert 'id="selectedNodeDetail"' in html
    assert "function renderSelectedNodeDetail" in html
    assert "renderSelectedNodeDetail();" in html
    assert "selectedNodeDetail" in html
