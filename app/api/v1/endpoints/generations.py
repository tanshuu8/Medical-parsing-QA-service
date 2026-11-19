"""Endpoints for executing LLM test case generations and checking staleness status."""
from typing import List, Optional
import uuid
import json
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.api.deps import get_db, get_mongodb_db, get_llm_service
from app.schemas.generation import QAGenerationCreate, QAGenerationResponse
from app.repositories.generation import generation_repo
from app.repositories.node import node_repo
from app.services.llm import LLMServiceInterface
from app.core.exceptions import ExternalServiceException
from app.models.node import Node
from app.models.document import Document

logger = logging.getLogger("app.api.generations")
router = APIRouter()


def check_staleness(db_sql: Session, record: dict) -> dict:
    """
    Compares the stashed content hashes of nodes in the generation
    against the hashes of corresponding logical nodes in the latest version of the document.
    
    ========================================================================
    STALENESS SYSTEM LIMITATIONS:
    
    1. Pure Syntactic vs Semantic Changes:
       Since staleness matches exact content hashes (MD5/SHA256), a minor typo correction or wording change
       (e.g., "clinical trial" -> "clinical study") changes the hash and triggers a STALE status. 
       The system cannot distinguish between semantic updates and simple formatting/wording changes.
       
    2. Missing Logical Links on Big Refactors:
       If sections are heavily merged or split, logical nodes can lose alignment links,
       triggering a false-positive STALE status labeled as REMOVED node.
    ========================================================================
    """
    doc_id_str = record.get("document_id")
    if not doc_id_str:
        return {"status": "UP_TO_DATE", "staleness_details": None}
        
    doc_id = uuid.UUID(str(doc_id_str))
    doc = db_sql.get(Document, doc_id)
    if not doc:
        return {"status": "UP_TO_DATE", "staleness_details": None}

    # Query the latest version of the same document (by name)
    query = select(Document).where(Document.name == doc.name).order_by(Document.created_at.desc())
    latest_doc = db_sql.scalars(query).first()
    
    if not latest_doc or latest_doc.id == doc.id:
        # This is already the latest document version
        return {"status": "UP_TO_DATE", "staleness_details": None}

    # Node IDs and stashed hashes
    node_ids_str = record.get("node_ids", [])
    node_ids = [uuid.UUID(str(nid)) for nid in node_ids_str]
    stashed_hashes = record.get("content_hashes", {})

    changed_nodes = []
    reasons = []

    for nid in node_ids:
        n1 = db_sql.get(Node, nid)
        if not n1:
            # Node no longer exists in SQL
            changed_nodes.append({
                "logical_node_id": None,
                "title": "Unknown Node",
                "change_type": "REMOVED"
            })
            reasons.append("Context node deleted.")
            continue

        # Find the matching node in the latest document using logical_node_id
        query_n2 = select(Node).where(
            Node.document_id == latest_doc.id,
            Node.logical_node_id == n1.logical_node_id
        )
        n2 = db_sql.scalars(query_n2).first()

        stashed_hash = stashed_hashes.get(str(nid)) or n1.content_hash

        if not n2:
            # Node exists in V1 but was deleted/removed in latest version
            changed_nodes.append({
                "logical_node_id": str(n1.logical_node_id),
                "title": n1.title,
                "change_type": "REMOVED"
            })
            reasons.append(f"Section '{n1.title}' was deleted.")
        elif n2.content_hash != stashed_hash:
            # Node exists but has different content hash (modified text)
            changed_nodes.append({
                "logical_node_id": str(n1.logical_node_id),
                "title": n2.title,
                "change_type": "MODIFIED"
            })
            reasons.append(f"Section '{n2.title}' was modified.")

    if changed_nodes:
        diff_summary = " ".join(reasons)
        return {
            "status": "STALE",
            "staleness_details": {
                "reason": f"Document context has changed in the latest version (v{latest_doc.version}).",
                "changed_nodes": changed_nodes,
                "diff_summary": diff_summary
            }
        }

    return {"status": "UP_TO_DATE", "staleness_details": None}


@router.post("/", response_model=QAGenerationResponse, status_code=status.HTTP_201_CREATED)
async def generate_qa_output(
    *,
    db_sql: Session = Depends(get_db),
    db_mongo: AsyncIOMotorDatabase = Depends(get_mongodb_db),
    document_id: uuid.UUID,
    prompt: str,
    node_ids: Optional[List[uuid.UUID]] = Query(None, description="Optional subset of specific Node IDs to generate QA Test Cases for"),
    selection_id: Optional[uuid.UUID] = None,
    llm: LLMServiceInterface = Depends(get_llm_service)
) -> QAGenerationResponse:
    """
    Generate 3-5 structured QA Test Cases using Google Gemini.
    Validates output JSON and retries on errors. If both attempts fail,
    logs details in MongoDB 'generation_failures' collection and returns a 502 Bad Gateway error.
    """
    # 1. Fetch document contexts from SQLite
    if node_ids:
        query = select(Node).where(Node.id.in_(node_ids))
        nodes = list(db_sql.scalars(query).all())
        
        found_ids = {node.id for node in nodes}
        missing_ids = set(node_ids) - found_ids
        if missing_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Mismatched Node IDs: {[str(mid) for mid in missing_ids]} do not exist."
            )
    else:
        nodes = node_repo.get_by_document_id(db_sql, document_id=document_id)
        if not nodes:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No document context nodes found to feed LLM prompt."
            )
            
    target_node_ids = [node.id for node in nodes]
    stashed_hashes = {str(node.id): node.content_hash for node in nodes}

    # 2. Invoke Gemini QA Test Case generation
    try:
        qa_data = llm.generate_qa_test_cases(nodes)
        logger.info("Successfully generated structured QA Test Cases.")
    except ExternalServiceException as exc:
        logger.error(f"Structured LLM generation failed. Logging failure to MongoDB.")
        failure_log = {
            "document_id": str(document_id),
            "node_ids": [str(nid) for nid in target_node_ids],
            "selection_id": str(selection_id) if selection_id else None,
            "prompt": prompt,
            "error_message": exc.message,
            "details": exc.details,
            "created_at": datetime.now(timezone.utc)
        }
        await db_mongo["generation_failures"].insert_one(failure_log)
        raise exc

    # 3. Create the input schema for MongoDB storage
    generation_in = QAGenerationCreate(
        document_id=document_id,
        node_ids=target_node_ids,
        content_hashes=stashed_hashes,
        selection_id=selection_id,
        prompt=prompt,
        response=json.dumps(qa_data),
        model_name="gemini-1.5-flash",
        meta_info={
            "total_test_cases": len(qa_data.get("test_cases", []))
        }
    )
    
    # 4. Save to MongoDB
    record = await generation_repo.create(db_mongo, obj_in=generation_in)
    
    # Newly created generation is always up-to-date
    record["status"] = "UP_TO_DATE"
    record["staleness_details"] = None
    return record


@router.get("/", response_model=List[QAGenerationResponse])
async def read_generations(
    document_id: Optional[uuid.UUID] = None,
    db_sql: Session = Depends(get_db),
    db_mongo: AsyncIOMotorDatabase = Depends(get_mongodb_db)
) -> List[QAGenerationResponse]:
    """
    Query logged Gemini generation records from MongoDB, evaluating staleness status dynamically.
    """
    if document_id:
        records = await generation_repo.get_by_document(db_mongo, document_id=document_id)
    else:
        cursor = db_mongo[generation_repo.collection_name].find()
        records = []
        async for record in cursor:
            record["_id"] = str(record["_id"])
            records.append(record)
            
    # Process staleness checks dynamically
    output_records = []
    for r in records:
        staleness = check_staleness(db_sql, r)
        r.update(staleness)
        output_records.append(r)
        
    return output_records


@router.get("/{generation_id}", response_model=QAGenerationResponse)
async def read_generation(
    generation_id: str,
    db_sql: Session = Depends(get_db),
    db_mongo: AsyncIOMotorDatabase = Depends(get_mongodb_db)
) -> QAGenerationResponse:
    """
    Retrieve single LLM generation record detail by its MongoDB ID, evaluating staleness status dynamically.
    """
    record = await generation_repo.get(db_mongo, id=generation_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Generation record not found"
        )
        
    staleness = check_staleness(db_sql, record)
    record.update(staleness)
    return record
