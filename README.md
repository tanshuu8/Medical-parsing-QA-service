# AI Medical Device Ingestion & QA Generation Service

A production-quality RAG (Retrieval-Augmented Generation) backend system designed for medical device manuals. The application parses complex PDF layouts, constructs hierarchical text trees, tracks user highlights, aligns segments across document versions using fuzzy math, generates structured QA test cases via Google Gemini, and dynamically detects context staleness when document updates are uploaded.

---

## Technology Stack

- **FastAPI**: Asynchronous high-performance web framework.
- **SQLAlchemy ORM (SQLite)**: Relational database mapping structural entities (`Document`, `Node`, `Selection`, `SelectionNode`). SQLite is configured with `check_same_thread=False` to safely support concurrent asynchronous requests.
- **MongoDB (Motor Client)**: Document-oriented database for logging semi-structured LLM generations and tracking parsing failure diagnostics.
- **Google Gemini API**: Generates professional verification test cases using structured JSON output prompts.
- **PyMuPDF (fitz)**: Extracts text blocks, font sizes, coordinates, images, and tables from PDFs.
- **RapidFuzz**: Evaluates text edit similarity scores to link nodes across document revisions.
- **pytest**: Framework for unit and integration testing.

---

## Architectural Layout

The system implements a **Layered Clean Architecture** separating domain logic, data persistence, external service interfaces, and routing:

```text
app/
├── core/         # Bootstrapping: logging, databases connection pools, global exception handlers, settings.
├── models/       # Domain Database entities (SQLAlchemy ORM models).
├── schemas/      # Input/Output data validation objects (Pydantic DTOs).
├── repositories/ # Data Access Objects (DAOs) isolating SQL/NoSQL transaction queries.
├── services/     # Core integrations (Google Gemini, RapidFuzz alignments, PyMuPDF parser).
└── api/          # Dependency injections (deps.py) and versioned routers (/api/v1/).
```

---

## Installation & Running

### 1. Requirements Setup
Ensure Python 3.10+ is installed on your host system:
```bash
python -m pip install -r requirements.txt
```

### 2. Environment Variables Configuration

Copy the configuration template into your local `.env`:
```bash
cp .env.example .env
```
Configure `.env` variables:
```ini
PROJECT_NAME="AI Medical Parsing & QA Service"
API_V1_STR="/api/v1"
LOG_LEVEL="INFO"

# SQLite DB Connection (Use 3 slashes for relative path, 4 for absolute)
DATABASE_URL="sqlite:///./sql_app.db"

# MongoDB DB Connection
MONGODB_URL="mongodb://localhost:27017"
MONGODB_DB_NAME="medical_ai_db"

# Google Gemini Credentials
GEMINI_API_KEY="YOUR_GEMINI_API_KEY"
GEMINI_MODEL="gemini-1.5-flash"
```

### 3. Start Development Server
```bash
uvicorn app.main:app --reload
```
Navigate to the interactive documentation:
- Swagger Docs: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

### 4. Run Test Suite
```bash
python -m pytest tests/
```

---

## API Reference & Examples

### 1. Ingest PDF Document
- **Endpoint**: `POST /api/v1/documents/`
- **Description**: Ingests a medical device PDF manual via `multipart/form-data`. Saves the binary stream to a secure temporary file, parses its hierarchical trees recursively using PyMuPDF, and auto-aligns it to previous versions if they exist. The temporary file is securely deleted immediately after parsing.
- **Request Parameters (Form)**:
  - `file`: `UploadFile` (the PDF binary file payload)
  - `version`: `str` (the version string, e.g. `1.0.0`)
- **Curl Example**:
  ```bash
  curl -X POST "http://127.0.0.1:8000/api/v1/documents/" \
       -H "accept: application/json" \
       -H "Content-Type: multipart/form-data" \
       -F "file=@insulin_pump_manual.pdf" \
       -F "version=1.0.0"
  ```
- **Response** (HTTP 201):
  ```json
  {
    "name": "insulin_pump_manual.pdf",
    "version": "1.0.0",
    "id": "e3b0c442-98fc-1c14-9afb-f4c8996fb924",
    "created_at": "2026-07-17T17:00:00Z"
  }
  ```


---

### 2. Record User Selection
- **Endpoint**: `POST /api/v1/selection/`
- **Description**: Creates a user selection highlight. Selection is version-pinned and strictly validated against node document identifiers and target versions.
- **Request Body**:
  ```json
  {
    "name": "Basal Rate Selection",
    "document_version": "1.0.0",
    "node_ids": [
      "391287b3-30e4-4917-befe-07d66cfe78c3"
    ]
  }
  ```
- **Response** (HTTP 201):
  ```json
  {
    "id": "a9a8b7c6-d5e4-f3g2-h1i0-j9k8l7m6n5o4",
    "name": "Basal Rate Selection",
    "document_version": "1.0.0",
    "created_at": "2026-07-17T17:05:00Z",
    "node_ids": [
      "391287b3-30e4-4917-befe-07d66cfe78c3"
    ]
  }
  ```

---

### 3. Generate QA Test Cases
- **Endpoint**: `POST /api/v1/generations/`
- **Description**: Generates 3-5 QA test cases using Google Gemini from selected nodes. Output is validated against a strict JSON schema. If parsing fails, the backend retries once. Double failures log error traces in MongoDB.
- **Query Parameters**:
  - `document_id`: `e3b0c442-98fc-1c14-9afb-f4c8996fb924`
  - `prompt`: `"Verify insulin delivery calculations"`
- **Response** (HTTP 201):
  ```json
  {
    "id": "60c72b2f9b1d8e25b084c5a7",
    "document_id": "e3b0c442-98fc-1c14-9afb-f4c8996fb924",
    "node_ids": [
      "391287b3-30e4-4917-befe-07d66cfe78c3"
    ],
    "selection_id": null,
    "prompt": "Verify insulin delivery calculations",
    "response": "{\"test_cases\": [{\"title\": \"Verify basal delivery rates check\", \"precondition\": \"Device is initialized.\", \"steps\": [\"Step 1\"], \"expected_result\": \"Basal rate applies.\", \"traceability\": \"Basal Delivery Specifications\"}]}",
    "model_name": "gemini-1.5-flash",
    "meta_info": {
      "total_test_cases": 1
    },
    "created_at": "2026-07-17T17:10:00Z",
    "status": "UP_TO_DATE",
    "staleness_details": null
  }
  ```

---

### 4. Fetch Generation & Check Staleness
- **Endpoint**: `GET /api/v1/generations/{generation_id}`
- **Description**: Retrieves a QA generation log, dynamically comparing stored context hashes against matching logical nodes in the latest document version.
- **Response (If latest version modified nodes)**:
  ```json
  {
    "id": "60c72b2f9b1d8e25b084c5a7",
    "document_id": "e3b0c442-98fc-1c14-9afb-f4c8996fb924",
    "node_ids": [
      "391287b3-30e4-4917-befe-07d66cfe78c3"
    ],
    "prompt": "Verify insulin delivery calculations",
    "response": "...",
    "model_name": "gemini-1.5-flash",
    "created_at": "2026-07-17T17:10:00Z",
    "status": "STALE",
    "staleness_details": {
      "reason": "Document context has changed in the latest version (v2.0.0).",
      "changed_nodes": [
        {
          "logical_node_id": "b7d68a2f-1290-482a-bc90-fa128dc90ba4",
          "title": "Basal Delivery Specifications",
          "change_type": "MODIFIED"
        }
      ],
      "diff_summary": "Section 'Basal Delivery Specifications' was modified."
    }
  }
  ```

---

## Core System Workflows

### 1. Document Versioning & Matching Workflow
When uploading a new document version (e.g. V2), the system does not overwrite the existing V1 records. It ingests V2, and if V1 is found, it performs node alignment:
- Identifies exact matches via cryptographic `content_hash` (tagged `UNCHANGED`).
- Runs **RapidFuzz** comparing titles and recursively reconstructed breadcrumb paths (`Root > Section > Title`) to match modified segments (tagged `MODIFIED`).
- Assigns matching `logical_node_id`s to the newly aligned V2 nodes.
- Saves a summary report of the version diff inside the MongoDB `document_diffs` collection.

### 2. Selection & Validation Workflow
- Selection captures highlights spanning multiple document nodes.
- When creating a selection, the system validates that all provided node IDs exist, belong to a single document, and that the parent document's version matches the selection's `document_version` payload (version pinning constraint).
- Ingesting V2 has no side effects on V1 selections since the selection is pinned to V1's document version.

### 3. Staleness Detection Workflow
- When retrieving generations via `GET /generations/` or `GET /generations/{id}`, the system checks the SQLite database for a newer version of the parent document.
- It maps the generation's context nodes using their `logical_node_id`s to the latest document version.
- It compares the stashed `content_hashes` in the generation against the latest version's node hashes. If a mismatch is found or a node was deleted, the generation's status is returned as `STALE`, along with a unified diff summary.
- The generation is not automatically updated, allowing the user to review the changes before deciding whether to re-run the QA test case generator.
