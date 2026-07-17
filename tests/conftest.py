import pytest
from typing import Generator
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base
from app.api.deps import get_db, get_pdf_parser, get_mongodb_db
from app.services.pdf_parser import PDFParserInterface, ParsedNode


# 1. Setup in-memory SQLite connection for testing
TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# Mock MongoDB class for testing without external services
class MockMongoDB:
    def __init__(self):
        self.storage = {}

    async def insert_one(self, document_data):
        from bson import ObjectId
        obj_id = ObjectId()
        document_data["_id"] = obj_id
        self.storage[str(obj_id)] = document_data
        
        class InsertResult:
            inserted_id = obj_id
            
        return InsertResult()

    async def find_one(self, query):
        key = str(query.get("_id"))
        return self.storage.get(key)

    def find(self, query=None):
        query = query or {}
        doc_id = query.get("document_id")
        
        class AsyncCursor:
            def __init__(self, items):
                self.items = items
                
            def __aiter__(self):
                return self
                
            async def __anext__(self):
                if not self.items:
                    raise StopAsyncIteration
                return self.items.pop(0)
                
        items = list(self.storage.values())
        if doc_id:
            items = [item for item in items if item.get("document_id") == doc_id]
            
        return AsyncCursor(items)


class MockMongoCollectionManager:
    def __init__(self):
        self.db_instance = MockMongoDB()

    def __getitem__(self, name):
        return self.db_instance


class MockPDFParser(PDFParserInterface):
    def parse_document(self, file_path: str) -> list[ParsedNode]:
        root = ParsedNode(title="Mock Section H1", body="", level=0, page_number=1)
        child = ParsedNode(title="Mock Subsection H2", body="Mock body content text.", level=1, page_number=1)
        root.add_child(child)
        return [root]


@pytest.fixture(scope="function")
def db_session() -> Generator:
    """
    Creates SQL tables and yields an isolated SQLAlchemy database session for each test run.
    """
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session) -> Generator[TestClient, None, None]:
    """
    FastAPI client overridden with test SQLite database and mock MongoDB connections.
    """
    # Instantiate mock db once per test function so both POST and GET request refer to same storage
    mock_mongo_db = MockMongoCollectionManager()

    # Overriding get_db dependency
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    # Overriding get_mongodb_db dependency
    async def override_get_mongodb_db():
        return mock_mongo_db

    # Overriding get_pdf_parser dependency
    def override_get_pdf_parser():
        return MockPDFParser()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_mongodb_db] = override_get_mongodb_db
    app.dependency_overrides[get_pdf_parser] = override_get_pdf_parser

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
