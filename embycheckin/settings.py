from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


AIProvider = Literal["openai", "gemini", "claude"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db_path: str = Field(default="data/scheduler.db", validation_alias="DB_PATH")
    bind_host: str = Field(default="127.0.0.1", validation_alias="BIND_HOST")
    bind_port: int = Field(default=8000, validation_alias="BIND_PORT")
    tz: str = Field(default="Asia/Shanghai", validation_alias="TZ")

    api_id: Optional[int] = Field(default=None, validation_alias="API_ID")
    api_hash: Optional[str] = Field(default=None, validation_alias="API_HASH")

    ai_provider: AIProvider = Field(default="openai", validation_alias="AI_PROVIDER")
    ai_ssl_verify: bool = Field(default=True, validation_alias="AI_SSL_VERIFY")
    ai_ca_file: Optional[str] = Field(default=None, validation_alias="AI_CA_FILE")

    openai_base_url: str = Field(default="https://api.openai.com/v1", validation_alias="OPENAI_BASE_URL")
    openai_api_key: Optional[str] = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", validation_alias="OPENAI_MODEL")

    gemini_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta",
        validation_alias="GEMINI_BASE_URL",
    )
    gemini_api_key: Optional[str] = Field(default=None, validation_alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", validation_alias="GEMINI_MODEL")

    claude_base_url: str = Field(default="https://api.anthropic.com", validation_alias="CLAUDE_BASE_URL")
    claude_api_key: Optional[str] = Field(default=None, validation_alias="CLAUDE_API_KEY")
    claude_model: str = Field(default="claude-3-5-sonnet-20241022", validation_alias="CLAUDE_MODEL")
    claude_max_tokens: int = Field(default=200, validation_alias="CLAUDE_MAX_TOKENS")

    @field_validator("db_path")
    @classmethod
    def _normalize_db_path(cls, value: str) -> str:
        return (value or "").strip() or "data/scheduler.db"

    @property
    def database_url(self) -> str:
        if self.db_path.startswith("sqlite:"):
            return self.db_path
        return f"sqlite:///{Path(self.db_path).resolve()}"


settings = Settings()
