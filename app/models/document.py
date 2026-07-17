import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class Document(Base):
    """
    SQLAlchemy model representing an ingested PDF document.
    
    Relationships:
    - nodes: One-to-Many. Represents the connection from a document to its parsed constituent pieces (chunks).
             When a document is removed, the constituent text chunks must also be removed (cascade delete).
    """
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, 
        primary_key=True, 
        default=uuid.uuid4, 
        index=True,
        comment="Unique identifier for the document"
    )
    name: Mapped[str] = mapped_column(
        String(255), 
        nullable=False,
        comment="Name of the document file"
    )
    version: Mapped[str] = mapped_column(
        String(50), 
        nullable=False,
        comment="Version string of the document"
    )
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc), 
        nullable=False,
        comment="Timestamp of document ingestion with microsecond-level precision"
    )

    # Relationships
    nodes: Mapped[list["Node"]] = relationship(
        "Node",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select"
    )

    def __repr__(self) -> str:
        return f"<Document id={self.id} name='{self.name}' version='{self.version}'>"
