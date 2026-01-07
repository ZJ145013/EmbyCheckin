from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskCreate(BaseModel):
    name: str = Field(min_length=1)
    type: str = Field(min_length=1)
    enabled: bool = True
    account_id: Optional[int] = None
    target: Optional[str] = None
    schedule_cron: str = Field(min_length=1)
    timezone: str = "Asia/Shanghai"
    jitter_seconds: int = 0
    max_runtime_seconds: int = 120
    retries: int = 0
    retry_backoff_seconds: int = 30
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_required_fields(self):
        if self.type != "emby_keepalive":
            if self.account_id is None:
                raise ValueError("account_id is required for this task type")
            if not self.target:
                raise ValueError("target is required for this task type")
        return self


class TaskUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    account_id: Optional[int] = None
    target: Optional[str] = None
    schedule_cron: Optional[str] = None
    timezone: Optional[str] = None
    jitter_seconds: Optional[int] = None
    max_runtime_seconds: Optional[int] = None
    retries: Optional[int] = None
    retry_backoff_seconds: Optional[int] = None
    params: Optional[dict[str, Any]] = None


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: str
    enabled: bool
    account_id: Optional[int]
    target: Optional[str]
    schedule_cron: str
    timezone: str
    jitter_seconds: int
    max_runtime_seconds: int
    retries: int
    retry_backoff_seconds: int
    params: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    status: str
    attempt: int
    triggered_by: str
    scheduled_for: Optional[datetime]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    duration_ms: Optional[int]
    error_message: Optional[str]
    result: dict[str, Any]
    created_at: datetime


class AccountCreate(BaseModel):
    name: str = Field(min_length=1)
    session_name: str = Field(min_length=1)


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    session_name: str
    created_at: datetime
    updated_at: datetime
