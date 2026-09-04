"""Application configuration using Pydantic Settings."""

import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str = ""

    # Database: Loaded strictly from .env / environment variables (no hardcoded credentials)
    DATABASE_URL: str = ""
    POSTGRES_SYNC_URL: str = ""
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    # Redis: Loaded from .env / environment variables
    REDIS_URL: str = "redis://127.0.0.1:6379/0"

    # LLM Gateway
    LLM_PROVIDER: str = "groq"
    # Google Gemini
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_PROJECT_ID: Optional[str] = None
    GEMINI_PROJECT_NO: Optional[str] = None

    # Groq
    GROQ_API_KEY: str = ""
    GROQ_ROUTING_MODEL: str = "openai/gpt-oss-20b"
    GROQ_REASONING_MODEL: str = "openai/gpt-oss-120b"

    # Rate Limiting
    RATE_LIMIT_IP_PER_MINUTE: int = 100
    RATE_LIMIT_CUSTOMER_PER_MINUTE: int = 30

    # HITL Thresholds
    FRAUD_RISK_HITL_THRESHOLD: float = 0.80
    TRANSFER_STEP_UP_LIMIT: float = 50000.00

    # LangSmith Tracing & Evaluation
    LANGCHAIN_TRACING_V2: str = "true"
    LANGCHAIN_ENDPOINT: str = "https://api.smith.langchain.com"
    LANGCHAIN_API_KEY: Optional[str] = None
    LANGCHAIN_PROJECT: str = "novabank-agent-prod"


settings = Settings()

# Propagate Gemini configuration into os.environ
if settings.GEMINI_API_KEY:
    os.environ["GEMINI_API_KEY"] = settings.GEMINI_API_KEY
if settings.GEMINI_MODEL:
    os.environ["GEMINI_MODEL"] = settings.GEMINI_MODEL

# Propagate LangSmith configuration into os.environ for native LangGraph/LangChain tracing
if settings.LANGCHAIN_API_KEY:
    os.environ["LANGCHAIN_TRACING_V2"] = settings.LANGCHAIN_TRACING_V2
    os.environ["LANGCHAIN_ENDPOINT"] = settings.LANGCHAIN_ENDPOINT
    os.environ["LANGCHAIN_API_KEY"] = settings.LANGCHAIN_API_KEY
    os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT

