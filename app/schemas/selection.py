import uuid
import re
from datetime import datetime
from typing import List
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SelectionBase(BaseModel):
    """Base attributes for user node highlight selections."""
    name: str = Field(..., max_length=255, description="Name of the selection")
    document_version: str = Field(..., max_length=50, description="Version of the document on which selection was made")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Selection name cannot be empty or only whitespace.")
        return clean

    @field_validator("document_version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Document version cannot be empty or only whitespace.")
        if not re.match(r"^[a-zA-Z0-9.\-_]+$", clean):
            raise ValueError("Document version contains invalid characters. Only alphanumeric, dots, dashes, and underscores are allowed.")
        return clean


class SelectionCreate(SelectionBase):
    node_ids: List[uuid.UUID] = Field(..., min_length=1, description="List of Node UUIDs associated with this selection")


class SelectionResponse(SelectionBase):
    id: uuid.UUID
    created_at: datetime
    node_ids: List[uuid.UUID] = Field(default=[], description="List of linked Node UUIDs")

    model_config = ConfigDict(from_attributes=True)


class SelectionNodeMappingResponse(BaseModel):
    selection_id: uuid.UUID
    node_id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)
