import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class Selection(Base):
    """Represents a version-pinned user highlight across one or more document nodes."""
    """
    SQLAlchemy model representing a user selection/highlight.
    
    Relationships:
    - nodes: Many-to-Many. A user's selection might overlap with multiple text nodes.
             Conversely, a node can be referenced by multiple selections.
    """
    __tablename__ = "selections"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, 
        primary_key=True, 
        default=uuid.uuid4, 
        index=True,
        comment="Unique identifier for the user selection"
    )
    name: Mapped[str] = mapped_column(
        String(255), 
        nullable=False,
        comment="Name of the selection"
    )
    document_version: Mapped[str] = mapped_column(
        String(50), 
        nullable=False,
        comment="Target version of the document on which selection was made"
    )
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc), 
        nullable=False,
        comment="Timestamp of selection record creation with microsecond-level precision"
    )

    # Relationships
    nodes: Mapped[list["Node"]] = relationship(
        "Node", 
        secondary="selection_nodes", 
        back_populates="selections",
        lazy="select"
    )

    def __repr__(self) -> str:
        return f"<Selection id={self.id} name='{self.name}' doc_version='{self.document_version}'>"
