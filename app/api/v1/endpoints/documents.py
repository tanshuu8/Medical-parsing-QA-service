import os
import tempfile
from typing import List, Optional
import uuid
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import select
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.api.deps import get_db, get_pdf_parser, get_mongodb_db, get_version_matcher
from app.schemas.document import DocumentCreate, DocumentResponse
from app.repositories.document import document_repo
from app.repositories.node import node_repo
from app.services.pdf_parser import PDFParserInterface, ParsedNode
from app.services.version_matcher import VersionMatcherInterface
from app.models.document import Document
from app.models.node import Node

logger = logging.getLogger("app.api.documents")
router = APIRouter()


def save_parsed_tree(
    db: Session,
    parsed_nodes: List[ParsedNode],
    document_id: uuid.UUID,
    parent_id: Optional[uuid.UUID] = None,
    nodes_to_add: Optional[List[Node]] = None
) -> List[Node]:
    """
    Recursively builds Node model objects, pre-generating Python-level UUIDs
    to allow batch database writes in a single commit.
    """
    if nodes_to_add is None:
        nodes_to_add = []
        
    for p_node in parsed_nodes:
        node_uuid = uuid.uuid4()
        db_node = Node(
            id=node_uuid,
            document_id=document_id,
            logical_node_id=uuid.uuid4(),
            parent_id=parent_id,
            title=p_node.title,
            body=p_node.body,
            level=p_node.level,
            page_number=p_node.page_number,
            content_hash=p_node.content_hash
        )
        nodes_to_add.append(db_node)

        if p_node.children:
            save_parsed_tree(
                db, 
                p_node.children, 
                document_id=document_id, 
                parent_id=node_uuid,
                nodes_to_add=nodes_to_add
            )
            
    return nodes_to_add


@router.post("/", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_document(
    *,
    db: Session = Depends(get_db),
    db_mongo: AsyncIOMotorDatabase = Depends(get_mongodb_db),
    file: UploadFile = File(...),
    version: str = Form(...),
    parser: PDFParserInterface = Depends(get_pdf_parser),
    matcher: VersionMatcherInterface = Depends(get_version_matcher)
) -> DocumentResponse:
    """
    Ingest a new PDF Document structure via multipart/form-data upload.
    Recursively saves parsed hierarchy nodes, and performs version match comparisons 
    against previous versions of the same file name, if any.
    """
    # Instantiate the schemas validator internally
    try:
        document_in = DocumentCreate(name=file.filename, version=version)
    except Exception as validation_err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Validation failed: {validation_err}"
        )

    # 1. Check for duplicate upload of SAME version
    existing_doc = document_repo.get_by_name_and_version(
        db, 
        name=document_in.name, 
        version=document_in.version
    )
    if existing_doc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document with this name and version already exists."
        )

    query = select(Document).where(
        Document.name == document_in.name,
        Document.version != document_in.version
    ).order_by(Document.created_at.desc())
    prev_doc = db.scalars(query).first()

    # 2. Save the UploadFile bytes to a secure temporary file
    temp_file_path = None
    parsed_tree = []
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            temp_file_path = tmp.name

        # Parse structural text tree from the temporary file path
        logger.info(f"Triggering PDF structural parsing for uploaded file: {file.filename}")
        parsed_tree = parser.parse_document(temp_file_path)
    except Exception as e:
        logger.error(f"Failed to parse uploaded PDF document {file.filename}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed parsing PDF file structures. Detail: {e}"
        )
    finally:
        # Securely delete the temporary file immediately after parsing to save disk space
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
                logger.info(f"Successfully cleaned up temporary upload file at: {temp_file_path}")
            except Exception as err:
                logger.error(f"Failed to delete temporary file {temp_file_path}: {err}")

    # 3. Create Document entry in SQLite
    doc = document_repo.create(db, obj_in=document_in)

    # 4. Save parsing tree recursively in one transaction
    try:
        flat_nodes = save_parsed_tree(db, parsed_tree, document_id=doc.id)
        db.add_all(flat_nodes)
        db.commit()
        logger.info(f"Successfully batch-saved {len(flat_nodes)} parsed nodes for document: {doc.id}")
    except Exception as e:
        logger.exception(f"Database insertion failed while saving parsed nodes for document {doc.id}")
        db.rollback()  # Rollback first to make the session operational
        # Clean up orphaned document header
        document_repo.remove(db, id=doc.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal database persistence failure while saving parsing tree."
        )

    # 5. Perform Version Match Alignment if an older version exists
    if prev_doc:
        logger.info(f"Detected previous version '{prev_doc.version}' for document '{doc.name}'. Executing node alignments.")
        try:
            v1_nodes = node_repo.get_by_document_id(db, document_id=prev_doc.id)
            v2_nodes = node_repo.get_by_document_id(db, document_id=doc.id)

            alignment_summary = matcher.align_versions(db, nodes_v1=v1_nodes, nodes_v2=v2_nodes)

            diff_record = {
                "document_name": doc.name,
                "v1_version": prev_doc.version,
                "v2_version": doc.version,
                "v1_document_id": str(prev_doc.id),
                "v2_document_id": str(doc.id),
                "summary": {
                    "total_nodes_v1": alignment_summary["total_nodes_v1"],
                    "total_nodes_v2": alignment_summary["total_nodes_v2"],
                    "unchanged": alignment_summary["unchanged_count"],
                    "modified": alignment_summary["modified_count"],
                    "new": alignment_summary["new_count"],
                    "removed": alignment_summary["removed_count"]
                },
                "nodes": alignment_summary["nodes"],
                "created_at": datetime.now(timezone.utc)
            }
            await db_mongo["document_diffs"].insert_one(diff_record)
            logger.info("Saved version alignment diff report inside MongoDB document_diffs collection.")
        except Exception as ex:
            logger.error(f"Version alignment algorithm execution failed for document {doc.name}: {ex}")
            db.rollback()

    return doc


@router.get("/", response_model=List[DocumentResponse])
def read_documents(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100
) -> List[DocumentResponse]:
    """
    Retrieve list of uploaded documents.
    """
    return document_repo.get_multi(db, skip=skip, limit=limit)


@router.get("/{document_id}", response_model=DocumentResponse)
def read_document_by_id(
    document_id: uuid.UUID,
    db: Session = Depends(get_db)
) -> DocumentResponse:
    """
    Get details of a single document by UUID.
    """
    doc = document_repo.get(db, id=document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    return doc


@router.delete("/{document_id}", response_model=DocumentResponse)
def delete_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db)
) -> DocumentResponse:
    """
    Delete a document and cascade delete its associated nodes.
    """
    doc = document_repo.get(db, id=document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    return document_repo.remove(db, id=document_id)
