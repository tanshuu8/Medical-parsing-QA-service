import uuid
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models.node import Node


def test_generation_staleness_lifecycle(client: TestClient, db_session: Session) -> None:
    """
    Test the Generation Staleness Detection pipeline:
      - Creating a generation initially returns UP_TO_DATE.
      - Uploading a V2 document with modified nodes triggers STALE.
    """
    # ----------------------------------------------------
    # Step 1: Ingest Document Version 1
    # ----------------------------------------------------
    files_v1 = {"file": ("clinical_trial_protocol.pdf", b"mocked pdf v1 bytes", "application/pdf")}
    data_v1 = {"version": "1.0.0"}
    v1_res = client.post("/api/v1/documents/", files=files_v1, data=data_v1)
    assert v1_res.status_code == 201
    doc_id_v1 = v1_res.json()["id"]

    # Retrieve created nodes (inserted by MockPDFParser: Mock Section H1, Mock Subsection H2)
    nodes_res = client.get("/api/v1/nodes/", params={"document_id": doc_id_v1})
    assert nodes_res.status_code == 200
    v1_nodes = nodes_res.json()
    assert len(v1_nodes) == 2
    
    h1_node_id = v1_nodes[0]["id"]
    h2_node_id = v1_nodes[1]["id"]

    # ----------------------------------------------------
    # Step 2: Trigger QA Test Cases Generation (UP_TO_DATE)
    # ----------------------------------------------------
    gen_params = {
        "document_id": doc_id_v1,
        "prompt": "Verify patient safety check rules",
        "node_ids": [h1_node_id, h2_node_id]
    }
    gen_res = client.post("/api/v1/generations/", params=gen_params)
    assert gen_res.status_code == 201
    gen_data = gen_res.json()
    assert gen_data["status"] == "UP_TO_DATE"
    assert gen_data["staleness_details"] is None
    generation_id = gen_data["_id"]

    # Retrieve generation details - should be UP_TO_DATE
    get_res = client.get(f"/api/v1/generations/{generation_id}")
    assert get_res.status_code == 200
    assert get_res.json()["status"] == "UP_TO_DATE"

    # ----------------------------------------------------
    # Step 3: Ingest Document Version 2 (triggers parsing & auto alignment)
    # ----------------------------------------------------
    files_v2 = {"file": ("clinical_trial_protocol.pdf", b"mocked pdf v2 bytes", "application/pdf")}
    data_v2 = {"version": "2.0.0"}
    v2_res = client.post("/api/v1/documents/", files=files_v2, data=data_v2)
    assert v2_res.status_code == 201
    doc_id_v2 = v2_res.json()["id"]

    # Let's query the newly created V2 nodes and manually modify a content hash in SQLite
    # to simulate content changes without node duplication
    v2_uuid = uuid.UUID(doc_id_v2)
    v2_nodes_query = select(Node).where(Node.document_id == v2_uuid)
    db_v2_nodes = list(db_session.scalars(v2_nodes_query).all())
    assert len(db_v2_nodes) == 2

    # Change the first V2 node's content hash
    db_v2_nodes[0].content_hash = "modified_hash_val_xxx"
    db_session.add(db_v2_nodes[0])
    db_session.commit()
    db_session.expire_all()

    # ----------------------------------------------------
    # Step 4: Verify Retrieval reflects STALE due to modification
    # ----------------------------------------------------
    get_res_stale = client.get(f"/api/v1/generations/{generation_id}")
    assert get_res_stale.status_code == 200
    stale_data = get_res_stale.json()
    
    assert stale_data["status"] == "STALE"
    assert stale_data["staleness_details"] is not None
    assert "changed_nodes" in stale_data["staleness_details"]
    
    changed = stale_data["staleness_details"]["changed_nodes"]
    assert len(changed) == 1
    assert changed[0]["change_type"] == "MODIFIED"
    assert changed[0]["title"] == "Mock Section H1"
