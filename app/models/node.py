import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Text, ForeignKey, Uuid, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class Node(Base):
    """Represents a structural element (heading, section, table) within a document."""
    """
    SQLAlchemy model representing a parsed text block/chunk from a document.
    
    Relationships:
    - document: Many-to-One. Points back to the parent Document entity.
    - parent & children: Self-referential hierarchy. Organizes text chunks hierarchically (e.g. section titles vs paragraphs).
      If a parent node is deleted, its sub-nodes should cascade delete (cascade="all, delete-orphan").
    - selections: Many-to-Many. Links text selections to the nodes they overlap.
    """
    __tablename__ = "nodes"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, 
        primary_key=True, 
        default=uuid.uuid4, 
        index=True,
        comment="Unique identifier for the parsed node chunk"
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, 
        ForeignKey("documents.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True,
        comment="Foreign key referencing parent Document"
    )
    logical_node_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, 
        default=uuid.uuid4, 
        nullable=False, 
        index=True,
        comment="Logical ID tracking nodes across document versions"
    )
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, 
        ForeignKey("nodes.id", ondelete="CASCADE"), 
        nullable=True, 
        index=True,
        comment="Self-referencing foreign key for hierarchical structure"
    )
    title: Mapped[str] = mapped_column(
        String(255), 
        nullable=False,
        comment="Heading title of the chunk"
    )
    body: Mapped[str] = mapped_column(
        Text, 
        nullable=False,
        comment="Raw text body content of the chunk"
    )
    level: Mapped[int] = mapped_column(
        Integer, 
        nullable=False,
        comment="Hierarchy depth level (e.g., 0 for H1, 1 for H2)"
    )
    page_number: Mapped[int] = mapped_column(
        Integer, 
        nullable=False, 
        index=True,
        comment="Page number in source PDF"
    )
    content_hash: Mapped[str] = mapped_column(
        String(64), 
        nullable=False, 
        index=True,
        comment="Hash code of the content body to check for modifications"
    )
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc), 
        nullable=False,
        comment="Creation timestamp with microsecond-level precision"
    )

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="nodes")
    
    parent: Mapped[Optional["Node"]] = relationship(
        "Node", 
        back_populates="children", 
        remote_side=[id]
    )
    
    children: Mapped[list["Node"]] = relationship(
        "Node", 
        back_populates="parent", 
        cascade="all, delete-orphan", 
        passive_deletes=True
    )
    
    selections: Mapped[list["Selection"]] = relationship(
        "Selection", 
        secondary="selection_nodes", 
        back_populates="nodes",
        lazy="select"
    )

    def __repr__(self) -> str:
        return f"<Node id={self.id} title='{self.title}' doc_id={self.document_id} level={self.level}>"
