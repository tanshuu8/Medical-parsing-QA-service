from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.core.logging import logger


class AppException(Exception):
    """Base application exception class."""
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class EntityNotFoundException(AppException):
    """Raised when a requested database entity is not found (HTTP 404)."""
    def __init__(self, message: str = "Entity not found"):
        super().__init__(message, status_code=404)


class EntityAlreadyExistsException(AppException):
    """Raised when an entity already exists in database."""
    def __init__(self, message: str = "Entity already exists"):
        super().__init__(message, status_code=400)


class ExternalServiceException(AppException):
    """Raised when an external API (like Gemini) fails."""
    def __init__(self, message: str = "External service integration error", details: dict = None):
        super().__init__(message, status_code=502)
        self.details = details or {}


def register_exception_handlers(app: FastAPI) -> None:
    """Register custom application exception handlers within FastAPI."""
    
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        logger.error(f"AppException occurred: {exc.message} [Code: {exc.status_code}]")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": {
                    "type": exc.__class__.__name__,
                    "message": exc.message
                }
            }
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("An unhandled exception occurred in the application")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": {
                    "type": "InternalServerError",
                    "message": "An unexpected error occurred on the server."
                }
            }
        )
