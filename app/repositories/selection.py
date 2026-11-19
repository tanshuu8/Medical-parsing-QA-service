from typing import List, Optional
import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.selection import Selection
from app.models.selection_node import SelectionNode
from app.models.node import Node
from app.schemas.selection import SelectionCreate
from app.repositories.base import BaseRepository


class SelectionRepository(BaseRepository[Selection, SelectionCreate, SelectionCreate]):
    """Repository managing Selection entities and association table linkages."""
    def __init__(self):
        super().__init__(Selection)

    def get_by_document_version(self, db: Session, *, document_version: str) -> List[Selection]:
        """
        Retrieve all selections associated with a document version.
        """
        query = select(self.model).where(self.model.document_version == document_version)
        return list(db.scalars(query).all())

    def create_selection_with_nodes(
        self, db: Session, *, obj_in: SelectionCreate, matched_nodes: List[Node]
    ) -> Selection:
        """
        Creates a Selection record and associates it with multiple Nodes.
        Ensures atomic transactions.
        """
        obj_in_data = obj_in.model_dump(exclude={"node_ids"})
        
        # 1. Create selection database object
        db_obj = self.model(**obj_in_data)
        
        # 2. Bind nodes relationship list
        db_obj.nodes = matched_nodes
        
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def get_mappings_for_selection(self, db: Session, *, selection_id: uuid.UUID) -> List[SelectionNode]:
        """
        Retrieve all mapped node relations for a specific user selection.
        """
        query = select(SelectionNode).where(SelectionNode.selection_id == selection_id)
        return list(db.scalars(query).all())


selection_repo = SelectionRepository()
