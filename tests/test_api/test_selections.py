import uuid
from fastapi.testclient import TestClient


def test_selection_lifecycle_and_validation(client: TestClient) -> None:
    """
    Test the Selection API lifecycle (create with validations, fetch, delete).
    """
    # 1. Post document payload (V1) as multipart upload
    files = {"file": ("manual.pdf", b"mocked pdf bytes content", "application/pdf")}
    data = {"version": "1.0.0"}
    doc_res = client.post("/api/v1/documents/", files=files, data=data)
    assert doc_res.status_code == 201
    doc_id = doc_res.json()["id"]

    # 2. Add structural nodes
    node_payload_1 = {
        "document_id": doc_id,
        "title": "Heading 1",
        "body": "Introductory scope guidelines text.",
        "level": 0,
        "page_number": 1,
        "content_hash": "hash_node_a1"
    }
    node_payload_2 = {
        "document_id": doc_id,
        "title": "Subheading 1.1",
        "body": "Detailed checklist specifications.",
        "level": 1,
        "page_number": 1,
        "content_hash": "hash_node_a2"
    }
    n1_res = client.post("/api/v1/nodes/", json=node_payload_1)
    n2_res = client.post("/api/v1/nodes/", json=node_payload_2)
    assert n1_res.status_code == 201
    assert n2_res.status_code == 201
    node_id_1 = n1_res.json()["id"]
    node_id_2 = n2_res.json()["id"]

    # --- Test Case A: Valid Selection Creation ---
    selection_payload = {
        "name": "Sample Selection Range",
        "document_version": "1.0.0",
        "node_ids": [node_id_1, node_id_2]
    }
    sel_res = client.post("/api/v1/selection/", json=selection_payload)
    assert sel_res.status_code == 201
    sel_data = sel_res.json()
    assert sel_data["name"] == selection_payload["name"]
    assert sel_data["document_version"] == "1.0.0"
    assert node_id_1 in sel_data["node_ids"]
    assert node_id_2 in sel_data["node_ids"]
    selection_id = sel_data["id"]

    # --- Test Case B: Non-existent Node IDs (400 Bad Request) ---
    invalid_node_id = str(uuid.uuid4())
    invalid_payload = {
        "name": "Invalid Selection",
        "document_version": "1.0.0",
        "node_ids": [node_id_1, invalid_node_id]
    }
    invalid_res = client.post("/api/v1/selection/", json=invalid_payload)
    assert invalid_res.status_code == 400
    assert "do not exist" in invalid_res.json()["detail"]

    # --- Test Case C: Version Pinning Mismatch (400 Bad Request) ---
    mismatch_payload = {
        "name": "Mismatch Version Selection",
        "document_version": "2.0.0",  # Mismatch (nodes belong to 1.0.0)
        "node_ids": [node_id_1, node_id_2]
    }
    mismatch_res = client.post("/api/v1/selection/", json=mismatch_payload)
    assert mismatch_res.status_code == 400
    assert "version mismatch" in mismatch_res.json()["detail"].lower()

    # --- Test Case D: Fetch Selection (GET /selection/{id}) ---
    get_res = client.get(f"/api/v1/selection/{selection_id}")
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["name"] == "Sample Selection Range"
    assert len(get_data["node_ids"]) == 2

    # --- Test Case E: Delete Selection (DELETE /selection/{id}) ---
    del_res = client.delete(f"/api/v1/selection/{selection_id}")
    assert del_res.status_code == 200

    # Verify deleted selection is missing
    missing_res = client.get(f"/api/v1/selection/{selection_id}")
    assert missing_res.status_code == 404
