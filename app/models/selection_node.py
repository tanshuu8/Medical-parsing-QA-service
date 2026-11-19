import uuid
from sqlalchemy import ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class SelectionNode(Base):
    """Association table linking Selection entities to their included Node records."""
    """
    SQLAlchemy association model linking Selection to Nodes (Many-to-Many junction).
    Uses composite keys as primary keys and indexes.
    
    If either a Selection or a Node is deleted, the corresponding junction is cascadingly deleted.
    """
    __tablename__ = "selection_nodes"

    selection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, 
        ForeignKey("selections.id", ondelete="CASCADE"), 
        primary_key=True,
        index=True,
        comment="Foreign key referencing Selection"
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, 
        ForeignKey("nodes.id", ondelete="CASCADE"), 
        primary_key=True,
        index=True,
        comment="Foreign key referencing Node"
    )

    def __repr__(self) -> str:
        return f"<SelectionNode selection_id={self.selection_id} node_id={self.node_id}>"
