from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from sqlmodel import Session, select

from ..models import Task
from ..runner import TaskRunner


class SchedulerService:
    def __init__(
        self,
        *,
        runner: TaskRunner,
        session_factory: Callable[[], Session],
    ) -> None:
        self._runner = runner
        self._session_factory = session_factory
        self._scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        self._job_ids: dict[int, str] = {}

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("Scheduler started")

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    async def reload_all(self) -> None:
        for job_id in list(self._job_ids.values()):
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass
        self._job_ids.clear()

        with self._session_factory() as session:
            tasks = session.exec(select(Task).where(Task.enabled == True)).all()

        for task in tasks:
            self._add_job(task)

        logger.info(f"Reloaded {len(tasks)} tasks")

    def _add_job(self, task: Task) -> None:
        try:
            parts = task.schedule_cron.split()
            if len(parts) == 5:
                trigger = CronTrigger(
                    minute=parts[0],
                    hour=parts[1],
                    day=parts[2],
                    month=parts[3],
                    day_of_week=parts[4],
                    timezone=task.timezone,
                )
            else:
                logger.error(f"Invalid cron expression for task {task.id}: {task.schedule_cron}")
                return

            job_id = f"task_{task.id}"
            self._scheduler.add_job(
                self._execute_task,
                trigger=trigger,
                args=[task.id],
                id=job_id,
                replace_existing=True,
                misfire_grace_time=300,
            )
            self._job_ids[task.id] = job_id
            logger.debug(f"Added job for task {task.id}: {task.name}")

        except Exception as e:
            logger.error(f"Failed to add job for task {task.id}: {e}")

    async def _execute_task(self, task_id: int) -> None:
        try:
            await self._runner.run_task(task_id=task_id, triggered_by="scheduler")
        except Exception as e:
            logger.error(f"Task {task_id} execution error: {e}")

    def add_task(self, task: Task) -> None:
        if task.enabled:
            self._add_job(task)

    def remove_task(self, task_id: int) -> None:
        job_id = self._job_ids.pop(task_id, None)
        if job_id:
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass

    def update_task(self, task: Task) -> None:
        self.remove_task(task.id)
        if task.enabled:
            self._add_job(task)

    async def run_now(self, task_id: int) -> int:
        return await self._runner.run_task(task_id=task_id, triggered_by="manual")
