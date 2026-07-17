from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import engine, Base
from app.core.mongodb import mongodb_manager
from app.core.logging import setup_logging, logger
from app.core.exceptions import register_exception_handlers
from app.api.v1.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages startup and shutdown lifecycles of databases and logging.
    """
    # 1. Setup logger configuration
    setup_logging()
    logger.info("Initializing application startup sequence.")

    # 2. Setup SQLite tables (simulating initial schema creation)
    logger.info("Creating relational database tables (SQLite).")
    Base.metadata.create_all(bind=engine)

    # 3. Connect to MongoDB connection pool
    logger.info("Connecting to MongoDB connection pool.")
    mongodb_manager.connect()

    yield  # Application processes requests here

    # 4. Clean up connection pool on shutdown
    logger.info("Initializing application shutdown sequence.")
    mongodb_manager.close()


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# Set all CORS enabled origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register custom global exceptions
register_exception_handlers(app)

# Include core routers
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/", tags=["health"])
def health_check():
    """
    Liveness probe endpoint.
    """
    return {
        "status": "healthy",
        "project": settings.PROJECT_NAME
    }
