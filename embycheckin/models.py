from datetime import datetime, timezone
from typing import Any, List, Optional

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, Relationship, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Account(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    session_name: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    tasks: List["Task"] = Relationship(back_populates="account")


class Task(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    type: str = Field(index=True)
    enabled: bool = Field(default=True, index=True)

    account_id: Optional[int] = Field(default=None, foreign_key="account.id", index=True)
    account: Optional["Account"] = Relationship(back_populates="tasks")

    target: Optional[str] = Field(default=None, index=True)
    schedule_cron: str = Field(index=True)
    timezone: str = Field(default="Asia/Shanghai")

    jitter_seconds: int = Field(default=0)
    max_runtime_seconds: int = Field(default=120)
    retries: int = Field(default=0)
    retry_backoff_seconds: int = Field(default=30)

    params: dict = Field(default_factory=dict, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    runs: List["TaskRun"] = Relationship(back_populates="task")


class TaskRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="task.id", index=True)
    task: Optional["Task"] = Relationship(back_populates="runs")

    status: str = Field(default="queued", index=True)
    attempt: int = Field(default=0)
    triggered_by: str = Field(default="scheduler", index=True)
    scheduled_for: Optional[datetime] = Field(default=None)

    started_at: Optional[datetime] = Field(default=None, index=True)
    finished_at: Optional[datetime] = Field(default=None, index=True)
    duration_ms: Optional[int] = Field(default=None)

    error_message: Optional[str] = Field(default=None)
    result: dict = Field(default_factory=dict, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=utcnow)
