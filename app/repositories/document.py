from typing import Optional
import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.document import Document
from app.schemas.document import DocumentCreate, DocumentUpdate
from app.repositories.base import BaseRepository


class DocumentRepository(BaseRepository[Document, DocumentCreate, DocumentUpdate]):
    def __init__(self):
        super().__init__(Document)

    def get_by_name_and_version(self, db: Session, *, name: str, version: str) -> Optional[Document]:
        """
        Retrieve a document by its name and version.
        """
        query = select(self.model).where(
            self.model.name == name,
            self.model.version == version
        )
        return db.scalars(query).first()


document_repo = DocumentRepository()
