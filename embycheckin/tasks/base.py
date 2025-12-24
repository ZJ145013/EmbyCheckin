from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel


C = TypeVar("C", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    id: int
    name: str
    type: str
    enabled: bool
    account_id: int
    target: str
    schedule_cron: str
    timezone: str
    jitter_seconds: int
    max_runtime_seconds: int
    retries: int
    retry_backoff_seconds: int
    params: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    id: int
    name: str
    session_name: str


@dataclass(slots=True)
class TaskContext:
    task: TaskSnapshot
    account: AccountSnapshot
    now: datetime
    settings: Any
    resources: dict[str, Any] = field(default_factory=dict)
    triggered_by: str = "scheduler"


@dataclass(slots=True)
class TaskResult:
    success: bool
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class TaskHandler(Generic[C], metaclass=abc.ABCMeta):
    type: ClassVar[str]
    ConfigModel: ClassVar[type[C]]

    @abc.abstractmethod
    async def execute(self, ctx: TaskContext, cfg: C) -> TaskResult:
        raise NotImplementedError


_TASK_HANDLERS: dict[str, type[TaskHandler[Any]]] = {}


def register_task_handler(handler_cls: type[TaskHandler[Any]]) -> type[TaskHandler[Any]]:
    task_type = getattr(handler_cls, "type", None)
    if not isinstance(task_type, str) or not task_type:
        raise ValueError("TaskHandler must define non-empty classvar `type`.")
    if task_type in _TASK_HANDLERS:
        raise ValueError(f"Duplicate task handler type: {task_type!r}")
    _TASK_HANDLERS[task_type] = handler_cls
    return handler_cls


def get_task_handler(task_type: str) -> TaskHandler[Any]:
    try:
        cls = _TASK_HANDLERS[task_type]
    except KeyError as e:
        known = ", ".join(sorted(_TASK_HANDLERS.keys()))
        raise KeyError(f"Unknown task type: {task_type!r}. Known: {known}") from e
    return cls()


def list_task_types() -> list[str]:
    return sorted(_TASK_HANDLERS.keys())


def validate_task_params(task_type: str, params: dict[str, Any]) -> BaseModel:
    handler_cls = _TASK_HANDLERS.get(task_type)
    if handler_cls is None:
        raise KeyError(f"Unknown task type: {task_type!r}")
    return handler_cls.ConfigModel.model_validate(params or {})
