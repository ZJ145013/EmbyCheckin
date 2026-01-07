from __future__ import annotations

import asyncio
import random
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlmodel import Session, select

from .models import Account, Task, TaskRun
from .tasks.base import (
    AccountSnapshot,
    TaskContext,
    TaskResult,
    TaskSnapshot,
    get_task_handler,
    validate_task_params,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskRunner:
    def __init__(
        self,
        *,
        settings: Any,
        session_factory: Callable[[], Session],
        resources: Optional[dict[str, Any]] = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._resources = resources or {}
        self._account_locks: dict[int, asyncio.Lock] = {}

    def _lock_for_account(self, account_id: int) -> asyncio.Lock:
        if account_id not in self._account_locks:
            self._account_locks[account_id] = asyncio.Lock()
        return self._account_locks[account_id]

    async def _db(self, fn: Callable[[Session], Any]) -> Any:
        def _run() -> Any:
            with self._session_factory() as session:
                try:
                    out = fn(session)
                    session.commit()
                    return out
                except Exception:
                    session.rollback()
                    raise
        return await asyncio.to_thread(_run)

    async def run_task(
        self,
        *,
        task_id: int,
        triggered_by: str = "scheduler",
        scheduled_for: Optional[datetime] = None,
    ) -> int:
        run_id: int = await self._db(
            lambda s: self._create_run_row(s, task_id, triggered_by, scheduled_for)
        )

        snapshot = await self._db(lambda s: self._load_snapshots(s, task_id))
        if snapshot is None:
            await self._db(lambda s: self._mark_run_failed(s, run_id, "Task not found"))
            return run_id

        task_snap, account_snap = snapshot

        if not task_snap.enabled:
            await self._db(lambda s: self._mark_run_skipped(s, run_id, "Task is disabled"))
            return run_id

        lock_key = task_snap.account_id if task_snap.account_id is not None else -task_snap.id
        lock = self._lock_for_account(lock_key)
        async with lock:
            # 首次执行前应用 jitter 延迟（手动触发时跳过）
            if task_snap.jitter_seconds > 0 and triggered_by != "manual":
                jitter = random.uniform(0.0, float(task_snap.jitter_seconds))
                await asyncio.sleep(jitter)

            start_time = time.perf_counter()
            await self._db(lambda s: self._mark_run_running(s, run_id))

            handler = get_task_handler(task_snap.type)
            max_attempts = max(1, 1 + int(task_snap.retries))
            last_error: Optional[str] = None

            for attempt in range(1, max_attempts + 1):
                await self._db(lambda s, a=attempt: self._set_run_attempt(s, run_id, a))

                try:
                    cfg = validate_task_params(task_snap.type, task_snap.params)
                    ctx = TaskContext(
                        task=task_snap,
                        account=account_snap,
                        now=utcnow(),
                        settings=self._settings,
                        resources={**self._resources, "runner": self},
                        triggered_by=triggered_by,
                    )
                    result: TaskResult = await asyncio.wait_for(
                        handler.execute(ctx, cfg), timeout=task_snap.max_runtime_seconds
                    )

                    if result.success:
                        duration_ms = int((time.perf_counter() - start_time) * 1000)
                        await self._db(lambda s: self._mark_run_success(s, run_id, result, duration_ms))
                        return run_id

                    last_error = result.message or "Task returned success=False"
                except asyncio.TimeoutError:
                    last_error = f"Timed out after {task_snap.max_runtime_seconds}s"
                except Exception as e:
                    last_error = f"{type(e).__name__}: {e}"

                if attempt < max_attempts:
                    await asyncio.sleep(self._compute_backoff(task_snap, attempt))

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            await self._db(lambda s: self._mark_run_failed(s, run_id, last_error or "Unknown error", duration_ms))
            return run_id

    def _compute_backoff(self, task: TaskSnapshot, attempt: int) -> float:
        base = max(0, int(task.retry_backoff_seconds))
        delay = base * (2 ** max(0, attempt - 1))
        delay += random.uniform(0.0, min(1.0, delay * 0.1 + 1.0))
        if task.jitter_seconds:
            delay += random.uniform(0.0, float(task.jitter_seconds))
        return float(delay)

    def _create_run_row(
        self, session: Session, task_id: int, triggered_by: str, scheduled_for: Optional[datetime]
    ) -> int:
        run = TaskRun(
            task_id=task_id,
            status="queued",
            attempt=0,
            triggered_by=triggered_by,
            scheduled_for=scheduled_for,
            created_at=utcnow(),
            result={},
        )
        session.add(run)
        session.flush()
        return int(run.id)

    def _load_snapshots(self, session: Session, task_id: int) -> Optional[tuple[TaskSnapshot, Optional[AccountSnapshot]]]:
        task = session.exec(select(Task).where(Task.id == task_id)).one_or_none()
        if task is None:
            return None

        account_snap: Optional[AccountSnapshot] = None
        if task.account_id is not None:
            account = session.exec(select(Account).where(Account.id == task.account_id)).one_or_none()
            if account:
                account_snap = AccountSnapshot(
                    id=int(account.id),
                    name=account.name,
                    session_name=account.session_name,
                )

        task_snap = TaskSnapshot(
            id=int(task.id),
            name=task.name,
            type=task.type,
            enabled=bool(task.enabled),
            account_id=task.account_id,
            target=task.target,
            schedule_cron=task.schedule_cron,
            timezone=task.timezone,
            jitter_seconds=int(task.jitter_seconds),
            max_runtime_seconds=int(task.max_runtime_seconds),
            retries=int(task.retries),
            retry_backoff_seconds=int(task.retry_backoff_seconds),
            params=dict(task.params or {}),
        )
        return task_snap, account_snap

    def _mark_run_running(self, session: Session, run_id: int) -> None:
        run = session.get(TaskRun, run_id)
        if run:
            run.status = "running"
            run.started_at = utcnow()

    def _set_run_attempt(self, session: Session, run_id: int, attempt: int) -> None:
        run = session.get(TaskRun, run_id)
        if run:
            run.attempt = attempt

    def _mark_run_success(self, session: Session, run_id: int, result: TaskResult, duration_ms: int) -> None:
        run = session.get(TaskRun, run_id)
        if run:
            run.status = "success"
            run.finished_at = utcnow()
            run.duration_ms = duration_ms
            run.error_message = None
            run.result = {"task_result": asdict(result)}

    def _mark_run_failed(
        self, session: Session, run_id: int, error_message: str, duration_ms: Optional[int] = None
    ) -> None:
        run = session.get(TaskRun, run_id)
        if run:
            run.status = "failed"
            run.finished_at = utcnow()
            if duration_ms is not None:
                run.duration_ms = duration_ms
            run.error_message = (error_message or "")[:2000]

    def _mark_run_skipped(self, session: Session, run_id: int, message: str) -> None:
        run = session.get(TaskRun, run_id)
        if run:
            run.status = "skipped"
            run.started_at = run.started_at or utcnow()
            run.finished_at = utcnow()
            run.error_message = (message or "")[:2000]
            run.result = {"skipped": True, "message": message}
