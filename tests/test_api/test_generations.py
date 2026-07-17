import uuid
from fastapi.testclient import TestClient


def test_generate_and_fetch_qa(client: TestClient) -> None:
    """
    Verifies full integration mock: creates document, nodes, queries LLM generation, and checks MongoDB retrieval.
    """
    # 1. First ingest a document via multipart upload
    files = {"file": ("oncology.pdf", b"mocked pdf bytes content", "application/pdf")}
    data = {"version": "1.0.0"}
    doc_response = client.post("/api/v1/documents/", files=files, data=data)
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # 2. Ingest document structural nodes
    node_payload = {
        "document_id": doc_id,
        "title": "Oncology Report Title",
        "body": "Oncology patient report detailing chemotherapy schedules.",
        "level": 0,
        "page_number": 1,
        "content_hash": "a1b2c3d4e5f60708090a1b2c3d4e5f60708090a1b2c3d4e5f60708090a1b2c3d"
    }
    node_response = client.post("/api/v1/nodes/", json=node_payload)
    assert node_response.status_code == 201

    # 3. Request LLM Generation
    gen_params = {
        "document_id": doc_id,
        "prompt": "Summarize patient oncology reports?"
    }
    gen_response = client.post("/api/v1/generations/", params=gen_params)
    assert gen_response.status_code == 201
    gen_data = gen_response.json()
    assert gen_data["prompt"] == gen_params["prompt"]
    assert "response" in gen_data
    assert gen_data["model_name"] == "gemini-1.5-flash"

    # 4. Fetch list of generations from MongoDB
    get_generations_response = client.get("/api/v1/generations/")
    assert get_generations_response.status_code == 200
    generations_list = get_generations_response.json()
    assert len(generations_list) == 1
    assert generations_list[0]["_id"] == gen_data["_id"]
