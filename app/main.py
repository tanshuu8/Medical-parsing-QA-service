from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

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


@app.get("/studio", response_class=HTMLResponse, tags=["studio"])
def read_studio():
    """
    Serves the AI QA Version Studio single page application wizard.
    """
    import os
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    html_path = os.path.join(static_dir, "studio.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read(), status_code=200)
    except FileNotFoundError:
        return HTMLResponse(content="<h1>AI QA Version Studio template not found.</h1>", status_code=404)


@app.get("/", tags=["health"])
def health_check():
    """
    Liveness probe endpoint.
    """
    return {
        "status": "healthy",
        "project": settings.PROJECT_NAME
    }

