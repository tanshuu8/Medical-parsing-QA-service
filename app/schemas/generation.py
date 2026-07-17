import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class QAGenerationBase(BaseModel):
    document_id: uuid.UUID = Field(..., description="Reference to SQL Document UUID")
    node_ids: List[uuid.UUID] = Field(default=[], description="List of SQL Node UUIDs utilized as context")
    content_hashes: Dict[str, str] = Field(default={}, description="Mapping of Node ID string to its content hash at time of generation")
    selection_id: Optional[uuid.UUID] = Field(default=None, description="Optional reference to SQL Selection UUID")
    prompt: str = Field(..., description="Prompt injected into the LLM")
    response: str = Field(..., description="Generated answer from the LLM")
    model_name: str = Field(..., description="Name of the Gemini model used (e.g. gemini-1.5-flash)")
    meta_info: Optional[Dict[str, Any]] = Field(default=None, description="Generation metadata")


class QAGenerationCreate(QAGenerationBase):
    pass


class QAGenerationResponse(QAGenerationBase):
    id: str = Field(..., alias="_id", description="MongoDB ObjectId as hex string")
    created_at: datetime
    status: str = Field(default="UP_TO_DATE", description="Status showing whether context nodes match the latest version: UP_TO_DATE or STALE")
    staleness_details: Optional[Dict[str, Any]] = Field(default=None, description="Detailed differences metadata block if status is STALE")

    # Allow mapping from MongoDB dict containing ObjectId
    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "id": "60c72b2f9b1d8e25b084c5a7",
                "document_id": "d3b0c442-98fc-1c14-9afb-f4c8996fb924",
                "node_ids": ["e3b0c442-98fc-1c14-9afb-f4c8996fb924"],
                "content_hashes": {"e3b0c442-98fc-1c14-9afb-f4c8996fb924": "hash_val"},
                "selection_id": "f3b0c442-98fc-1c14-9afb-f4c8996fb924",
                "prompt": "What is the diagnosis?",
                "response": "The diagnosis is diabetes mellitus type 2.",
                "model_name": "gemini-1.5-flash",
                "created_at": "2026-07-17T17:00:00Z",
                "status": "UP_TO_DATE"
            }
        }
    }
