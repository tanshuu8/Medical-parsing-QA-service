import uuid
import pytest
import time
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models.node import Node


def test_complete_end_to_end_walkthrough(client: TestClient, db_session: Session) -> None:
    """
    Principal Engineer Walkthrough Integration Test.
    Simulates the entire system lifecycle:
      1. Ingest V1 PDF Document -> automatic structural node parsing and hierarchy tree storage.
      2. Browse sections -> query and navigate parent-child relationships.
      3. Create user selection highlight -> pinned and validated to V1.0.0.
      4. Generate QA Test Cases -> triggers Gemini validation parsing, asserts UP_TO_DATE.
      5. Ingest V2 PDF Document -> runs fuzzy alignment mappings and maintains node link keys.
      6. Detect context changes -> dynamic staleness evaluation checks.
      7. Retrieve results -> returns STALE flag with changed details summary.
    """
    # ----------------------------------------------------
    # Phase 1: Ingest Document Version 1
    # ----------------------------------------------------
    files_v1 = {"file": ("insulin_pump_manual.pdf", b"mocked pdf v1 bytes", "application/pdf")}
    data_v1 = {"version": "1.0.0"}
    v1_res = client.post("/api/v1/documents/", files=files_v1, data=data_v1)
    assert v1_res.status_code == 201
    doc_id_v1 = v1_res.json()["id"]

    # ----------------------------------------------------
    # Phase 2: Browse Sections & Hierarchy
    # ----------------------------------------------------
    nodes_res = client.get("/api/v1/nodes/", params={"document_id": doc_id_v1})
    assert nodes_res.status_code == 200
    nodes = nodes_res.json()
    assert len(nodes) == 2  # Standard Mock Parser returns 2 nodes
    
    node_id_h1 = nodes[0]["id"]
    node_id_h2 = nodes[1]["id"]
    
    # Assert self-referencing tree parent-child pointers are preserved
    assert nodes[0]["parent_id"] is None  # H1 is root
    assert nodes[1]["parent_id"] == node_id_h1  # H2 points to H1

    # ----------------------------------------------------
    # Phase 3: Record User Selection Highlight (Pinned)
    # ----------------------------------------------------
    sel_payload = {
        "name": "Default Flow Highlight",
        "document_version": "1.0.0",
        "node_ids": [node_id_h2]
    }
    sel_res = client.post("/api/v1/selection/", json=sel_payload)
    assert sel_res.status_code == 201
    selection_id = sel_res.json()["id"]

    # ----------------------------------------------------
    # Phase 4: Generate QA Test Cases & Store Output
    # ----------------------------------------------------
    gen_params = {
        "document_id": doc_id_v1,
        "prompt": "Validate bolus insulin calculation accuracy",
        "node_ids": [node_id_h2],
        "selection_id": selection_id
    }
    gen_res = client.post("/api/v1/generations/", params=gen_params)
    assert gen_res.status_code == 201
    gen_data = gen_res.json()
    assert gen_data["status"] == "UP_TO_DATE"
    assert gen_data["staleness_details"] is None
    generation_id = gen_data["_id"]

    # ----------------------------------------------------
    # Phase 5: Ingest Document Version 2 (Auto alignments)
    # ----------------------------------------------------
    # Force clock resolution difference
    time.sleep(1.0)
    
    files_v2 = {"file": ("insulin_pump_manual.pdf", b"mocked pdf v2 bytes", "application/pdf")}
    data_v2 = {"version": "2.0.0"}
    v2_res = client.post("/api/v1/documents/", files=files_v2, data=data_v2)
    assert v2_res.status_code == 201
    doc_id_v2 = v2_res.json()["id"]

    # Get V2 nodes and manually simulate a content change inside SQLite
    v2_uuid = uuid.UUID(doc_id_v2)
    v2_nodes_query = select(Node).where(Node.document_id == v2_uuid)
    db_v2_nodes = list(db_session.scalars(v2_nodes_query).all())
    assert len(db_v2_nodes) == 2

    # Modify V2 node 2's content hash
    db_v2_nodes[1].content_hash = "modified_insulin_flow_hash_xxxx"
    db_session.add(db_v2_nodes[1])
    db_session.commit()
    db_session.expire_all()

    # ----------------------------------------------------
    # Phase 6: Dynamic Staleness Retrieval Checks
    # ----------------------------------------------------
    get_res = client.get(f"/api/v1/generations/{generation_id}")
    assert get_res.status_code == 200
    stale_data = get_res.json()
    
    # Verify expected staleness status and diff summary mapping outputs
    assert stale_data["status"] == "STALE"
    assert stale_data["staleness_details"] is not None
    assert stale_data["staleness_details"]["changed_nodes"][0]["change_type"] == "MODIFIED"
    assert stale_data["staleness_details"]["changed_nodes"][0]["title"] == "Mock Subsection H2"
    assert "modified" in stale_data["staleness_details"]["diff_summary"].lower()
