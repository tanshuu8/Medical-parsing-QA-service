from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.schemas.generation import QAGenerationCreate


class QAGenerationRepository:
    def __init__(self):
        self.collection_name = "qa_generations"

    async def create(self, db: AsyncIOMotorDatabase, *, obj_in: QAGenerationCreate) -> Dict[str, Any]:
        """
        Persists generated QA output record inside MongoDB.
        """
        document_data = obj_in.model_dump()
        document_data["created_at"] = datetime.now(timezone.utc)
        
        result = await db[self.collection_name].insert_one(document_data)
        document_data["_id"] = str(result.inserted_id)
        return document_data

    async def get(self, db: AsyncIOMotorDatabase, *, id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a single generation record by its string ObjectId.
        """
        if not ObjectId.is_valid(id):
            return None
            
        record = await db[self.collection_name].find_one({"_id": ObjectId(id)})
        if record:
            record["_id"] = str(record["_id"])
        return record

    async def get_by_document(self, db: AsyncIOMotorDatabase, *, document_id: uuid.UUID) -> List[Dict[str, Any]]:
        """
        Retrieve all generations linked to a specific SQL document UUID.
        """
        cursor = db[self.collection_name].find({"document_id": document_id})
        records = []
        async for record in cursor:
            record["_id"] = str(record["_id"])
            records.append(record)
        return records


generation_repo = QAGenerationRepository()
