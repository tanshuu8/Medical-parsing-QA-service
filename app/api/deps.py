from typing import AsyncGenerator, Generator
from sqlalchemy.orm import Session
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.mongodb import get_mongodb
from app.services.pdf_parser import PDFParserInterface, PDFParserService
from app.services.version_matcher import VersionMatcherInterface, VersionMatcherService
from app.services.llm import LLMServiceInterface, GeminiLLMService


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency injection provider yielding transactional SQLite sessions.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_mongodb_db() -> AsyncIOMotorDatabase:
    """
    FastAPI dependency injection provider yielding async MongoDB database instances.
    """
    return await get_mongodb()


def get_pdf_parser() -> PDFParserInterface:
    """
    Dependency injection provider yielding PDF Parser Service.
    """
    return PDFParserService()


def get_version_matcher() -> VersionMatcherInterface:
    """
    Dependency injection provider yielding version alignment matcher service.
    """
    return VersionMatcherService()


def get_llm_service() -> LLMServiceInterface:
    """
    Dependency injection provider yielding Gemini LLM execution service.
    """
    return GeminiLLMService(
        api_key=settings.GEMINI_API_KEY,
        default_model=settings.GEMINI_MODEL
    )
