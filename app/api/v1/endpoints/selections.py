from typing import List, Optional
import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.schemas.selection import SelectionCreate, SelectionResponse
from app.repositories.selection import selection_repo
from app.models.node import Node
from app.models.document import Document

logger = logging.getLogger("app.api.selections")
router = APIRouter()


@router.post("/", response_model=SelectionResponse, status_code=status.HTTP_201_CREATED)
def create_selection(
    *,
    db: Session = Depends(get_db),
    selection_in: SelectionCreate
) -> SelectionResponse:
    """
    Record user selection highlight. 
    Validates that:
      1. All node IDs exist in the database.
      2. All nodes belong to the same document.
      3. The parent document's version matches the selection's document_version.
    """
    # 1. Fetch nodes matching selection payload ids
    logger.info(f"Validating nodes selection inputs: {selection_in.node_ids}")
    query = select(Node).where(Node.id.in_(selection_in.node_ids))
    nodes = list(db.scalars(query).all())

    # Validation A: Node existence
    found_ids = {node.id for node in nodes}
    missing_ids = set(selection_in.node_ids) - found_ids
    if missing_ids:
        logger.error(f"Selection validation failed: missing nodes {missing_ids}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The following node IDs do not exist in the database: {[str(mid) for mid in missing_ids]}"
        )

    # Validation B: Single document association
    document_ids = {node.document_id for node in nodes}
    if len(document_ids) > 1:
        logger.error(f"Selection validation failed: nodes span multiple documents {document_ids}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="All selected nodes must belong to the same parent document."
        )

    # Validation C: Version pinning verification
    doc_id = list(document_ids)[0]
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resolve parent document metadata."
        )

    if doc.version != selection_in.document_version:
        logger.error(f"Version Mismatch: Selection pinned to version '{selection_in.document_version}', but target document version is '{doc.version}'")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Version mismatch constraint: Node document version '{doc.version}' does not match selection target version '{selection_in.document_version}'."
        )

    # 2. Transactionally save selection and many-to-many nodes relationship bindings
    selection = selection_repo.create_selection_with_nodes(
        db, 
        obj_in=selection_in, 
        matched_nodes=nodes
    )
    
    # Map back to matching output format
    response_data = SelectionResponse(
        id=selection.id,
        name=selection.name,
        document_version=selection.document_version,
        created_at=selection.created_at,
        node_ids=[node.id for node in nodes]
    )
    
    return response_data


@router.get("/{selection_id}", response_model=SelectionResponse)
def read_selection(
    selection_id: uuid.UUID,
    db: Session = Depends(get_db)
) -> SelectionResponse:
    """
    Get details of a single selection by database ID, including associated node IDs.
    """
    selection = selection_repo.get(db, id=selection_id)
    if not selection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Selection not found"
        )
        
    return SelectionResponse(
        id=selection.id,
        name=selection.name,
        document_version=selection.document_version,
        created_at=selection.created_at,
        node_ids=[node.id for node in selection.nodes]
    )


@router.delete("/{selection_id}", response_model=SelectionResponse)
def delete_selection(
    selection_id: uuid.UUID,
    db: Session = Depends(get_db)
) -> SelectionResponse:
    """
    Delete a selection and cascade delete its associated node links.
    """
    selection = selection_repo.get(db, id=selection_id)
    if not selection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Selection not found"
        )
        
    deleted_selection = selection_repo.remove(db, id=selection_id)
    return SelectionResponse(
        id=deleted_selection.id,
        name=deleted_selection.name,
        document_version=deleted_selection.document_version,
        created_at=deleted_selection.created_at,
        node_ids=[]
    )
