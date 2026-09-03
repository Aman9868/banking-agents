"""Application configuration using Pydantic Settings."""

import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str = "dev-secret-key-change-in-production-vault"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://user:gI7_36rpP_aQEj5FyJp9@127.0.0.1:5432/banking_agent_db"
    POSTGRES_SYNC_URL: str = "postgresql://user:gI7_36rpP_aQEj5FyJp9@127.0.0.1:5432/banking_agent_db"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    # Redis
    REDIS_URL: str = "redis://127.0.0.1:6379/0"

    # LLM Gateway
    LLM_PROVIDER: str = "groq"
    GROQ_API_KEY: str = ""
    GROQ_ROUTING_MODEL: str = "llama-3.1-8b-instant"
    GROQ_REASONING_MODEL: str = "llama-3.3-70b-versatile"

    # Rate Limiting
    RATE_LIMIT_IP_PER_MINUTE: int = 100
    RATE_LIMIT_CUSTOMER_PER_MINUTE: int = 30

    # HITL Thresholds
    FRAUD_RISK_HITL_THRESHOLD: float = 0.80
    TRANSFER_STEP_UP_LIMIT: float = 50000.00


settings = Settings()

