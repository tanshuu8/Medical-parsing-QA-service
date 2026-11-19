import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration settings loaded from environment variables."""
    # App Settings
    PROJECT_NAME: str = "AI Medical Parsing & QA Service"
    API_V1_STR: str = "/api/v1"
    LOG_LEVEL: str = "INFO"

    # SQLite database URL (default local storage file)
    # e.g., sqlite:///./sql_app.db
    DATABASE_URL: str = "sqlite:///./sql_app.db"

    # MongoDB settings for LLM generation storage
    MONGODB_URL: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "medical_ai_db"

    # Google Gemini API Config
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-1.5-flash"

    # Settings configurations
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()
