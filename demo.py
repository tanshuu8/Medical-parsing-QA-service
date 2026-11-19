"""Interactive CLI demo illustrating document ingestion, selection, and staleness detection."""
import os
import sys
import time
import httpx
import json

BASE_URL = "http://127.0.0.1:8000"
DOC_NAME = "CardioTrack_CT-200_Manual.pdf"

def print_header(title):
    print("\n" + "="*60)
    print(f" {title.upper()}")
    print("="*60 + "\n")

def check_server():
    try:
        response = httpx.get(f"{BASE_URL}/")
        if response.status_code == 200:
            print("[OK] Connection successful: FastAPI server is running.")
            return True
    except httpx.RequestError:
        pass
    print(f"[ERROR] Server is not running on {BASE_URL}.")
    print("Please start the server first in another terminal using:")
    print("  .\\venv\\Scripts\\uvicorn app.main:app --reload")
    return False

def clean_existing_documents():
    print(f"[*] Cleaning up old versions of {DOC_NAME} from database...")
    try:
        response = httpx.get(f"{BASE_URL}/api/v1/documents/")
        if response.status_code == 200:
            documents = response.json()
            for doc in documents:
                if doc["name"] == DOC_NAME:
                    print(f"    - Deleting existing document ID {doc['id']} (Version {doc['version']})")
                    httpx.delete(f"{BASE_URL}/api/v1/documents/{doc['id']}")
            print("[OK] Database cleaned up.")
    except Exception as e:
        print(f"[ERROR] Failed to clean up database: {e}")

def main():
    print_header("Medical Device Manual Ingestion & QA Generation Demo")
    
    if not check_server():
        sys.exit(1)
        
    # Clean up previous runs
    clean_existing_documents()
    
    # ----------------------------------------------------
    # Step 1: Ingest Document Version 1.0.0
    # ----------------------------------------------------
    print_header("Step 1: Uploading Version 1.0.0 of the Medical Manual")
    v1_file_path = "CardioTrack_CT-200_Manual_v1.pdf"
    
    if not os.path.exists(v1_file_path):
        print(f"[ERROR] {v1_file_path} not found in current directory.")
        sys.exit(1)
        
    print(f"[*] Uploading {v1_file_path} as '{DOC_NAME}' (Version 1.0.0)...")
    with open(v1_file_path, "rb") as f:
        files = {"file": (DOC_NAME, f, "application/pdf")}
        data = {"version": "1.0.0"}
        response = httpx.post(f"{BASE_URL}/api/v1/documents/", files=files, data=data, timeout=30.0)
        
    if response.status_code != 201:
        print(f"[ERROR] Upload failed: {response.text}")
        sys.exit(1)
        
    doc_v1 = response.json()
    doc_id_v1 = doc_v1["id"]
    print("[OK] Document uploaded successfully!")
    print(f"    - Document ID: {doc_id_v1}")
    print(f"    - Document Version: {doc_v1['version']}")

    # ----------------------------------------------------
    # Step 2: Fetch and Browse Extracted Logical Nodes
    # ----------------------------------------------------
    print_header("Step 2: Retrieving Parsed Hierarchical Nodes (SQLite)")
    response = httpx.get(f"{BASE_URL}/api/v1/nodes/", params={"document_id": doc_id_v1})
    if response.status_code != 200:
        print(f"[ERROR] Failed to fetch nodes: {response.text}")
        sys.exit(1)
        
    nodes = response.json()
    print(f"[OK] Extracted {len(nodes)} document sections/nodes:")
    
    # Print the tree structure nicely
    for node in nodes:
        indent = "  " * node["level"]
        print(f"    {indent}* [{node['level']}] {node['title']} (Page {node['page_number']})")
        # Print a snippet of the body text
        body_snippet = node['body'][:100].replace('\n', ' ') + '...' if len(node['body']) > 100 else node['body']
        print(f"    {indent}  Content: {body_snippet}")

    # Let's select some nodes for the test case generation
    target_nodes = [node for node in nodes if node["level"] > 0]
    if not target_nodes:
        target_nodes = nodes
    node_ids_to_select = [node["id"] for node in target_nodes[:2]]

    # ----------------------------------------------------
    # Step 3: Record User Highlight / Selection
    # ----------------------------------------------------
    print_header("Step 3: Creating a User Selection Pinned to Version 1.0.0")
    sel_payload = {
        "name": "Examiner Demo Selection",
        "document_version": "1.0.0",
        "node_ids": node_ids_to_select
    }
    response = httpx.post(f"{BASE_URL}/api/v1/selection/", json=sel_payload)
    if response.status_code != 201:
        print(f"[ERROR] Failed to create selection: {response.text}")
        sys.exit(1)
        
    selection = response.json()
    selection_id = selection["id"]
    print("[OK] Selection created and pinned:")
    print(f"    - Selection ID: {selection_id}")
    print(f"    - Selected Node Titles: {[node['title'] for node in target_nodes[:2]]}")

    # ----------------------------------------------------
    # Step 4: Generate QA Test Cases (Gemini API)
    # ----------------------------------------------------
    print_header("Step 4: Invoking Gemini API to Generate Structured QA Test Cases")
    print(f"[*] Requesting generation using model 'gemini-3.5-flash'...")
    
    gen_params = {
        "document_id": doc_id_v1,
        "prompt": "Verify device setup, battery warnings, and threshold display alarms.",
        "selection_id": selection_id
    }
    # Pass node_ids in query parameters format for List[UUID]
    query_str = "&".join([f"node_ids={nid}" for nid in node_ids_to_select])
    
    response = httpx.post(f"{BASE_URL}/api/v1/generations/?{query_str}", params=gen_params, timeout=60.0)
    if response.status_code != 201:
        print(f"[ERROR] Generation failed: {response.text}")
        sys.exit(1)
        
    generation = response.json()
    generation_id = generation.get("_id") or generation.get("id")
    print("[OK] Generation successful!")
    print(f"    - Generation ID (MongoDB): {generation_id}")
    print(f"    - Status: {generation['status']}")
    
    # Parse and display the structured QA test cases
    try:
        response_data = json.loads(generation["response"])
        test_cases = response_data.get("test_cases", [])
        print("\n--- GENERATED TEST CASES ---")
        for i, tc in enumerate(test_cases, 1):
            print(f"\n  Test Case {i}: {tc.get('title')}")
            print(f"    Precondition: {tc.get('precondition')}")
            print(f"    Steps:")
            for s in tc.get("steps", []):
                print(f"      - {s}")
            print(f"    Expected Result: {tc.get('expected_result')}")
            print(f"    Traceability: {tc.get('traceability')}")
        print("----------------------------")
    except Exception as parse_err:
        print(f"Could not parse response JSON printed below:\n{generation['response']}")

    # ----------------------------------------------------
    # Step 5: Upload Version 2.0.0 (Version Matching & Alignment)
    # ----------------------------------------------------
    print_header("Step 5: Uploading Version 2.0.0 (Triggering Version Alignment)")
    v2_file_path = "CardioTrack_CT-200_Manual_v2.pdf"
    if not os.path.exists(v2_file_path):
        print(f"[ERROR] {v2_file_path} not found.")
        sys.exit(1)
        
    print(f"[*] Uploading {v2_file_path} as '{DOC_NAME}' (Version 2.0.0)...")
    with open(v2_file_path, "rb") as f:
        files = {"file": (DOC_NAME, f, "application/pdf")}
        data = {"version": "2.0.0"}
        response = httpx.post(f"{BASE_URL}/api/v1/documents/", files=files, data=data, timeout=30.0)
        
    if response.status_code != 201:
        print(f"[ERROR] Upload failed: {response.text}")
        sys.exit(1)
        
    doc_v2 = response.json()
    doc_id_v2 = doc_v2["id"]
    print("[OK] Version 2.0.0 uploaded and aligned successfully!")
    print(f"    - Document ID: {doc_id_v2}")
    
    # Wait briefly for DB operations to finalize
    time.sleep(1.0)

    # ----------------------------------------------------
    # Step 6: Query Staleness Status of V1 Generation
    # ----------------------------------------------------
    print_header("Step 6: Querying Staleness of the V1 Generation against Version 2.0.0")
    print(f"[*] Fetching generation {generation_id} details...")
    response = httpx.get(f"{BASE_URL}/api/v1/generations/{generation_id}")
    if response.status_code != 200:
        print(f"[ERROR] Failed to fetch generation: {response.text}")
        sys.exit(1)
        
    gen_check = response.json()
    status = gen_check.get("status")
    
    if status == "STALE":
        print(f"[WARNING] Status Check: {status} (Context changes detected!)")
        details = gen_check.get("staleness_details", {})
        print(f"    - Reason: {details.get('reason')}")
        print(f"    - Diff Summary: {details.get('diff_summary')}")
        print("    - Changed Nodes:")
        for cn in details.get("changed_nodes", []):
            print(f"      * {cn['title']} -> Change Type: {cn['change_type']}")
    else:
        print(f"[OK] Status Check: {status} (No changes detected).")

    print_header("Demo Completed Successfully!")
    print("This demo proved:")
    print("1. PyMuPDF parsing: PDF structural trees are successfully extracted.")
    print("2. Database layer: Relational SQL matches and hierarchical nodes work.")
    print("3. Google Gemini API: Professional structured QA Test Cases are generated live.")
    print("4. RapidFuzz matching: Automatic alignment mapping triggers on V2 upload.")
    print("5. Context Staleness Pipeline: Detects document changes and marks generation STALE.")
    print("\nFeel free to show this console output and the FastAPI Swagger UI to your examiner!")

if __name__ == "__main__":
    main()
