"""Endpoints for retrieving hierarchical document nodes and outline structures."""
from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.schemas.node import NodeCreate, NodeResponse
from app.repositories.node import node_repo

router = APIRouter()


@router.post("/", response_model=NodeResponse, status_code=status.HTTP_201_CREATED)
def create_node(
    *,
    db: Session = Depends(get_db),
    node_in: NodeCreate
) -> NodeResponse:
    """
    Manually insert a parsed document text node chunk.
    """
    return node_repo.create(db, obj_in=node_in)


@router.get("/", response_model=List[NodeResponse])
def read_nodes(
    db: Session = Depends(get_db),
    document_id: Optional[uuid.UUID] = None,
    page_number: Optional[int] = None,
    skip: int = 0,
    limit: int = 100
) -> List[NodeResponse]:
    """
    Query parsed nodes, with optional filters for document ID and page number.
    """
    if document_id and page_number:
        return node_repo.get_by_page(db, document_id=document_id, page_number=page_number)
    elif document_id:
        return node_repo.get_by_document_id(db, document_id=document_id)
    return node_repo.get_multi(db, skip=skip, limit=limit)


@router.get("/{node_id}", response_model=NodeResponse)
def read_node(
    node_id: uuid.UUID,
    db: Session = Depends(get_db)
) -> NodeResponse:
    """
    Retrieve single node details.
    """
    node = node_repo.get(db, id=node_id)
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Node chunk not found"
        )
    return node
