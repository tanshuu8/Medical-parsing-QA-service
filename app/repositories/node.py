from typing import List
import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.node import Node
from app.schemas.node import NodeCreate
from app.repositories.base import BaseRepository


class NodeRepository(BaseRepository[Node, NodeCreate, NodeCreate]):
    def __init__(self):
        super().__init__(Node)

    def get_by_document_id(self, db: Session, *, document_id: uuid.UUID) -> List[Node]:
        """
        Retrieve all structural nodes for a given document.
        """
        # Node uses hierarchical sorting: level, title, page_number
        query = select(self.model).where(
            self.model.document_id == document_id
        ).order_by(self.model.page_number, self.model.level)
        return list(db.scalars(query).all())

    def get_by_page(self, db: Session, *, document_id: uuid.UUID, page_number: int) -> List[Node]:
        """
        Retrieve nodes on a specific page of a document.
        """
        query = select(self.model).where(
            self.model.document_id == document_id,
            self.model.page_number == page_number
        ).order_by(self.model.level)
        return list(db.scalars(query).all())


node_repo = NodeRepository()
