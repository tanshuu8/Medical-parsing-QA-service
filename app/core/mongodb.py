from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings
from app.core.logging import logger


class MongoDBManager:
    def __init__(self):
        self.client: AsyncIOMotorClient = None
        self.db = None

    def connect(self) -> None:
        """Initialize asynchronous Motor client connection pool to MongoDB."""
        logger.info(f"Connecting to MongoDB at: {settings.MONGODB_URL}")
        self.client = AsyncIOMotorClient(
            settings.MONGODB_URL,
            uuidRepresentation="standard"
        )
        self.db = self.client[settings.MONGODB_DB_NAME]
        logger.info(f"Successfully connected to MongoDB database: {settings.MONGODB_DB_NAME}")

    def close(self) -> None:
        """Close active Motor client connection pool."""
        if self.client:
            logger.info("Closing MongoDB connection pool.")
            self.client.close()
            self.client = None
            self.db = None
            logger.info("MongoDB connection pool closed.")


mongodb_manager = MongoDBManager()


async def get_mongodb():
    """
    Dependency utility to yield MongoDB database connection.
    """
    if mongodb_manager.db is None:
        # Fallback in case lifecycle events didn't run (e.g. testing)
        mongodb_manager.connect()
    return mongodb_manager.db
