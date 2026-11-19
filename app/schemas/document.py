import uuid
import re
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocumentBase(BaseModel):
    """Base schema attributes shared across document request and response models."""
    name: str = Field(..., max_length=255, description="Name of the document file")
    version: str = Field(..., max_length=50, description="Version code/tag of the document")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Document name cannot be empty or only whitespace.")
        if not clean.lower().endswith(".pdf"):
            raise ValueError("Only PDF documents are supported (.pdf extension required).")
        return clean

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Document version cannot be empty or only whitespace.")
        # Enforce safe semantic-like characters
        if not re.match(r"^[a-zA-Z0-9.\-_]+$", clean):
            raise ValueError("Document version contains invalid characters. Only alphanumeric, dots, dashes, and underscores are allowed.")
        return clean


class DocumentCreate(DocumentBase):
    pass


class DocumentUpdate(BaseModel):
    name: str | None = None
    version: str | None = None


class DocumentResponse(DocumentBase):
    id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
