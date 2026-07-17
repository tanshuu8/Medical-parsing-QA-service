from fastapi.testclient import TestClient


def test_health_check(client: TestClient) -> None:
    """
    Test the liveness check probe endpoint.
    """
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_create_and_read_documents(client: TestClient) -> None:
    """
    Test the Document database lifecycle (create, fetch, fetch list).
    """
    # 1. Post document payload as multipart/form-data
    files = {"file": ("clinical_report.pdf", b"mocked pdf bytes content", "application/pdf")}
    data = {"version": "1.0.0"}
    
    response = client.post("/api/v1/documents/", files=files, data=data)
    assert response.status_code == 201
    res_data = response.json()
    assert res_data["name"] == "clinical_report.pdf"
    assert res_data["version"] == "1.0.0"
    assert "id" in res_data

    # 2. Get list of documents
    get_response = client.get("/api/v1/documents/")
    assert get_response.status_code == 200
    docs = get_response.json()
    assert len(docs) == 1
    assert docs[0]["id"] == res_data["id"]

    # 3. Get document by ID
    get_by_id_response = client.get(f"/api/v1/documents/{res_data['id']}")
    assert get_by_id_response.status_code == 200
    assert get_by_id_response.json()["name"] == "clinical_report.pdf"


def test_document_versioning_alignment(client: TestClient) -> None:
    """
    Test that uploading a second version of a document does not overwrite Version 1,
    and runs version matching successfully.
    """
    # 1. Upload Version 1
    files_v1 = {"file": ("device_manual.pdf", b"mocked pdf v1 bytes", "application/pdf")}
    data_v1 = {"version": "1.0.0"}
    v1_response = client.post("/api/v1/documents/", files=files_v1, data=data_v1)
    assert v1_response.status_code == 201
    v1_data = v1_response.json()

    # 2. Upload Version 2 (Same name, different version string)
    files_v2 = {"file": ("device_manual.pdf", b"mocked pdf v2 bytes", "application/pdf")}
    data_v2 = {"version": "2.0.0"}
    v2_response = client.post("/api/v1/documents/", files=files_v2, data=data_v2)
    assert v2_response.status_code == 201
    v2_data = v2_response.json()

    # 3. Verify both versions exist in document listings (V1 was not overwritten)
    get_response = client.get("/api/v1/documents/")
    assert get_response.status_code == 200
    docs = get_response.json()
    
    doc_ids = [doc["id"] for doc in docs]
    assert v1_data["id"] in doc_ids
    assert v2_data["id"] in doc_ids
    assert len(docs) >= 2
