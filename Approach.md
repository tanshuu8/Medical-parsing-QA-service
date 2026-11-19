# Technical Approach & Design Log

This document details the architectural strategies, parsing heuristics, alignment pipelines, and design decisions implemented across the AI Medical Ingestion & QA Generation Service.

---

## 1. System Architecture

The project follows a **Layered Clean Architecture** and **Domain-Driven Design (DDD)** principles to separate infrastructure details from business domains.

```text
+---------------------------------------------------------+
|                  Presentation Layer                     |
|         (FastAPI Routers, Input/Output Schemas)         |
+----------------------------+----------------------------+
                             |
                             v
+---------------------------------------------------------+
|                    Services Layer                       |
|   (PDFParserService, VersionMatcher, GeminiLLMService)  |
+----------------------------+----------------------------+
                             |
                             v
+---------------------------------------------------------+
|                    Persistence Layer                    |
|    (Generic SQL Repositories, Motor Mongo Repository)   |
+----------------------------+----------------------------+
                             |
                             v
+---------------------------------------------------------+
|                    Databases Layer                      |
|       (SQLite Relational DB, MongoDB NoSQL DB)          |
+---------------------------------------------------------+
```

### Separation of Concerns:

- **Presentation**: FastAPI endpoints validate incoming request schemas using Pydantic DTOs and return structured JSON responses.
- **Domain Services**: Orchestrate business rules (reconstructing text, parsing layouts, evaluating fuzzy ratios, calling Gemini API) without being coupled to controllers or database drivers.
- **Repositories**: Standardize data mutations. The SQL repositories inherit from a generic CRUD repository, isolating session commits.

---

## 2. Ingestion & PDF Parser Strategy

### Secure Multipart Upload:
Document files are ingested via FastAPI `UploadFile` as `multipart/form-data`. The file bytes are streamed into a secure `tempfile.NamedTemporaryFile` with `delete=False`. The absolute file path is passed to the `PDFParserService` layout analyzer. Once parsing is complete, the temporary file is unlinked using `os.unlink` inside a guaranteed `finally` block, preventing disk space accumulation.

### Layout Analysis:
We parse PDFs using **PyMuPDF (`fitz`)** for high extraction performance and low-level access to font sizes, block coordinates, and span metadata. We read pages using `page.get_text("dict")`, which returns structural text blocks, lines, and spans. Spans capture `text`, `size`, and `flags` (indicating bold face, italicized options, etc.).

### Calibrating Headings:
To ensure the parser remains layout-agnostic, we run a preliminary **calibration pass** across the document to calculate font size frequencies:
- The statistical **mode** (most frequent font size) is designated as the standard body text size.
- **H1 Header threshold** is dynamically set to `body_size + 3.0pt`.
- **H2 Subheader threshold** is dynamically set to `body_size + 1.5pt`.
Spans with sizes exceeding these thresholds are classified as headings.

### Bounding-Box Table Filtering:
We call PyMuPDF's table grid detector `page.find_tables()`. Table grids are extracted and converted into Markdown tables. To prevent duplicate text extraction, we verify if block coordinates lie inside a table's bounding box; if they overlap, we skip parsing the raw text block, as the table parser already captured it.

### Caption Captures:
Lines matching regex patterns starting with `Figure X:`, `Fig. X:`, `Table X:` are isolated as captions.

### OCR Fallback Trigger:
If a page yields empty text spans (e.g. scanned documents), the system converts the page to a 150 DPI image byte stream. It triggers **pytesseract** OCR parsing to recover paragraphs, falling back to diagnostic warning logs if Tesseract is not installed on the host.

---

## 3. Hierarchy Tree Reconstruction

We map flat layout blocks into nested trees using a level-based **Parser Stack**:
1. Iterate over the parsed text blocks.
2. When encountering a Heading Node of level `L` (H1 = 0, H2 = 1):
   - Pop elements from the stack until finding an active parent header with a level less than `L`.
   - If a parent exists, append the new node to the parent's `children` relationship array.
   - If the stack is empty, add the new node as a root branch.
   - Push the new node onto the stack.
3. When encountering a standard Body/Table/Caption Node (level 2):
   - Locate the parent header at the top of the stack and append it as a child.
4. **Validation Utilities**: We enforce integrity using `validate_parsed_tree()`, which checks for circular dependencies, parent-child levels consistency, and duplicate node hashes.

---

## 4. Version Matching & Alignment

When a new version of a document is uploaded, we must align the new nodes to the older version's nodes without overwriting V1.

```text
V1 Doc (version: 1.0.0)             V2 Doc (version: 2.0.0)
+----------------------+            +----------------------+
| Node A (hash: x123)  | ---------> | Node A (hash: x123)  | -> UNCHANGED (logical_node_id copied)
+----------------------+            +----------------------+
| Node B (hash: y456)  | ---------> | Node B' (hash: y789) | -> MODIFIED  (logical_node_id copied)
+----------------------+            +----------------------+
| Node C (hash: z111)  |            | Node D (hash: w222)  | -> NEW       (logical_node_id generated)
+----------------------+            +----------------------+
(unmatched)                         (unmatched)            -> REMOVED
```

### Alignment Pipeline Steps:
- **Phase 1: Content Hash exact matches**
  - Matches nodes that have the same content hash and hierarchical breadcrumb path. These are tagged `UNCHANGED`.
- **Phase 2: Weighted Fuzzy Title + Path matches**
  - For modified nodes, we compute a combined similarity score using **RapidFuzz**:
    $$\text{Score} = (\text{Title Similarity} \times 0.6) + (\text{Breadcrumb Path Similarity} \times 0.4)$$
  - Title similarity is evaluated using `fuzz.token_sort_ratio`.
  - Breadcrumb path similarity compares the full hierarchy path (e.g. `Chapter 1 > Section 1.1 > Scope`). This prevents false positive matches on identical sub-headings (e.g. `Scope`) across different sections.
  - Matches scoring above `70%` are aligned and tagged `MODIFIED`.
- **Phase 3: New Nodes**
  - V2 nodes that have no matches are tagged `NEW` and generate their own logical tracking IDs.
- **Phase 4: Removed Nodes**
  - V1 nodes that are not matched to V2 are tagged `REMOVED`.

---

## 5. LLM Prompt Design & Retry Strategy

### System Prompt Design:
Instructs Gemini to act as a Senior Medical QA Engineer, generating 3 to 5 test cases from the context. We pass a structured JSON schema specification, configuring Gemini's `generation_config` with `response_mime_type="application/json"` to ensure syntactically valid JSON array strings.

### Structured Validation Check:
We check the parsed JSON output for required schema keys (`title`, `precondition`, `steps` as an array of strings, `expected_result`, and `traceability`), and verify that the test case count is between 3 and 5.

### Single-Retry Repair Loop:
1. If validation checks fail on the first attempt (e.g. missing keys or length violations), we log a warning.
2. We launch a second API call (Attempt 2) appending the parsing error warning directly to the prompt, instructing Gemini to correct the formatting.
3. If Attempt 2 also fails, we raise an `ExternalServiceException`. The API router catches the exception, logs all debugging parameters (prompt, attempt responses, error traces) in the MongoDB `generation_failures` collection, and returns an HTTP 502 Bad Gateway response.
4. This retry strategy balances reliability against latency.

---

## 6. Staleness Detection Strategy

Staleness checks identify if the source documentation used for a generation has changed in a subsequent version.

### Execution:
- The generation stores `node_ids` and the `content_hashes` of the context nodes at the time of execution inside MongoDB.
- On retrieval (`GET /generations/{id}`), we locate the latest version of the document in SQLite.
- For each node ID in the generation, we find its logical node ID and match it against the latest document version's nodes.
- If a hash has changed, the generation is marked `STALE` with a `MODIFIED` change type. If a node is missing in the latest version, it is flagged as `REMOVED`.
- The generation status is returned as `STALE`, along with a unified diff summary.

### Wording vs Semantic Changes (Limitations):
- **Wording Change**: Simple typo corrections or formatting edits change the cryptographic `content_hash` and trigger a `STALE` warning.
- **Semantic Change**: A core guideline update also changes the hash and triggers a `STALE` warning.
- **System boundary**: The system cannot distinguish semantic changes from spelling/formatting changes without introducing semantic evaluation overhead.

---

## 7. Architectural Decisions Log

1. **Relational vs Document Database Split**:
   - SQLite manages highly structured entities (`Document`, `Node`, `Selection`, `SelectionNode`). This ensures cascade-delete consistency and supports fast index joins.
   - MongoDB stores LLM generations and error logs. Since prompt structures, metadata, and token usage statistics change frequently, a flexible schema prevents SQL schema migration churn.
2. **Logical Node ID Tracking**:
   - Introducing `logical_node_id` allows us to track sections across revisions even if their database primary keys change. This decouples the identity of a section from its physical record, supporting staleness checks across versions.

---

## 8. Future Improvements

1. **Semantic Similarity Threshold Checks**:
   - Implement embedding models (e.g. Google Vertex AI) to compute cosine similarity on text changes. This will prevent false-positive staleness triggers on simple formatting/spelling edits.
2. **Alembic Database Migrations**:
   - Add Alembic to manage database migrations, supporting future relational schema updates without losing local data.
3. **LLM Output Streaming**:
   - Support streaming responses (`ResponseStream`) to reduce initial page load latency in front-end applications.

---

## 9. Decision Log (Required Questions)

### Q1: What's the one part of this system most likely to silently give wrong results without erroring? How would you catch it?
- **Answer**: The fuzzy matching version alignment scoring engine. If a heading is completely renamed and its paragraphs are rewritten, the alignment score falls below the threshold (70%). The engine silently classifies the old section as `REMOVED` and the new section as `NEW` (with a fresh `logical_node_id`). Consequently, any selection referencing the old section will look like it has no successor in V2, failing to flag the new version of this content as stale.
- **Detection**: We would log warnings detailing high volumes of unmatched nodes between revisions and set up automated alerts comparing V1 and V2 coordinate overlaps to catch potentially renamed sections.

### Q2: Where did you choose simplicity over correctness because of time, and what would break first if this went to production as-is?
- **Answer**: Cryptographic hashing (`content_hash`) for staleness detection. Any change (even a tiny typo correction or single space change) changes the hash and flags the generation as `STALE`.
- **Failure Mode**: In production, this causes high false-positive rates on simple spelling/formatting edits, leading to user warning fatigue and a drop in trust in the "Stale" indicator. The solution would be to use semantic text embedding similarity models.

### Q3: Name one input (to your parser, your versioning matcher, or your LLM call) that you did not handle, and what your system does when it sees it?
- **Answer**: Multiple identical headings in the same hierarchical level of a document (e.g. two separate sections both named "Alarm Limits" under the same parent chapter).
- **System Behavior**: Because the title and breadcrumb path are identical (e.g., `CardioTrack Manual > Alarm Limits`), the matching engine's Stage 2 fuzzy matcher will simply align the first node it queries in V1 with the first it queries in V2, potentially cross-matching them incorrectly if their layout order changed.
