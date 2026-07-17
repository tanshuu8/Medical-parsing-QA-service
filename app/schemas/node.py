import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class NodeBase(BaseModel):
    logical_node_id: Optional[uuid.UUID] = Field(default=None, description="Logical ID tracking nodes across document versions")
    parent_id: Optional[uuid.UUID] = Field(default=None, description="Parent node ID for hierarchy structures")
    title: str = Field(..., max_length=255, description="Heading title of the chunk")
    body: str = Field(..., description="Raw text body content of the chunk")
    level: int = Field(..., ge=0, description="Hierarchy depth level")
    page_number: int = Field(..., gt=0, description="1-indexed PDF page number")
    content_hash: str = Field(..., max_length=64, description="Hash code of the content body")


class NodeCreate(NodeBase):
    document_id: uuid.UUID = Field(..., description="Foreign key to target Document")


class NodeResponse(NodeBase):
    id: uuid.UUID
    document_id: uuid.UUID
    logical_node_id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
