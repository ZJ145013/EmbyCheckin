from __future__ import annotations

import asyncio
import re
import traceback
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, ValidationError
from sqlmodel import Session, select

from ..db import get_session
from ..models import Account, Task, TaskRun
from ..schemas import (
    AccountCreate,
    AccountResponse,
    TaskCreate,
    TaskUpdate,
    TaskResponse,
    RunResponse,
)
from ..tasks import list_task_types, validate_task_params


router = APIRouter(prefix="/api/v1")
SESSION_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")

_scheduler = None
_runner = None
_telegram_manager = None


def set_services(scheduler, runner, telegram_manager=None):
    global _scheduler, _runner, _telegram_manager
    _scheduler = scheduler
    _runner = runner
    _telegram_manager = telegram_manager


def get_db():
    with get_session() as session:
        yield session


@router.get("/status")
async def get_status():
    return {"status": "ok", "scheduler_running": _scheduler is not None}


@router.get("/task-types")
async def get_task_types():
    return {"types": list_task_types()}


@router.get("/tasks", response_model=list[TaskResponse])
async def list_tasks(
    enabled: Optional[bool] = None,
    type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = select(Task)
    if enabled is not None:
        query = query.where(Task.enabled == enabled)
    if type:
        query = query.where(Task.type == type)
    return db.exec(query).all()


@router.post("/tasks", response_model=TaskResponse)
async def create_task(data: TaskCreate, db: Session = Depends(get_db)):
    try:
        validate_task_params(data.type, data.params)
    except (KeyError, ValidationError) as e:
        raise HTTPException(400, str(e))

    account = db.get(Account, data.account_id)
    if not account:
        raise HTTPException(400, f"Account {data.account_id} not found")

    task = Task(**data.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)

    if _scheduler:
        _scheduler.add_task(task)

    return task


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(task_id: int, data: TaskUpdate, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    update_data = data.model_dump(exclude_unset=True)

    if "params" in update_data:
        try:
            validate_task_params(task.type, update_data["params"])
        except (KeyError, ValidationError) as e:
            raise HTTPException(400, str(e))

    for key, value in update_data.items():
        setattr(task, key, value)

    task.updated_at = datetime.now(timezone.utc)
    db.add(task)
    db.commit()
    db.refresh(task)

    if _scheduler:
        _scheduler.update_task(task)

    return task


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    if _scheduler:
        _scheduler.remove_task(task_id)

    # 先删除关联的执行记录
    runs = db.exec(select(TaskRun).where(TaskRun.task_id == task_id)).all()
    for run in runs:
        db.delete(run)

    db.delete(task)
    db.commit()
    return {"deleted": True}


@router.post("/tasks/{task_id}/run")
async def run_task_now(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    if not _scheduler:
        raise HTTPException(503, "Scheduler not available")

    asyncio.create_task(_scheduler.run_now(task_id))
    return {"queued": True, "task_id": task_id}


@router.get("/tasks/{task_id}/runs", response_model=list[RunResponse])
async def list_task_runs(task_id: int, limit: int = 20, db: Session = Depends(get_db)):
    limit = min(limit, 200)
    query = (
        select(TaskRun)
        .where(TaskRun.task_id == task_id)
        .order_by(TaskRun.created_at.desc())
        .limit(limit)
    )
    return db.exec(query).all()


@router.get("/runs", response_model=list[RunResponse])
async def list_runs(limit: int = 50, db: Session = Depends(get_db)):
    limit = min(limit, 200)
    query = select(TaskRun).order_by(TaskRun.created_at.desc()).limit(limit)
    return db.exec(query).all()


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(TaskRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@router.delete("/runs/{run_id}")
async def delete_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(TaskRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    db.delete(run)
    db.commit()
    return {"deleted": True}


class DeleteRunsRequest(BaseModel):
    ids: list[int]


@router.post("/runs/delete-batch")
async def delete_runs_batch(data: DeleteRunsRequest, db: Session = Depends(get_db)):
    if not data.ids:
        raise HTTPException(400, "No IDs provided")
    deleted = 0
    for run_id in data.ids:
        run = db.get(TaskRun, run_id)
        if run:
            db.delete(run)
            deleted += 1
    db.commit()
    return {"deleted": deleted}


@router.get("/accounts", response_model=list[AccountResponse])
async def list_accounts(db: Session = Depends(get_db)):
    return db.exec(select(Account)).all()


@router.post("/accounts", response_model=AccountResponse)
async def create_account(data: AccountCreate, db: Session = Depends(get_db)):
    if not SESSION_NAME_PATTERN.match(data.session_name):
        raise HTTPException(400, "Invalid session_name: only alphanumeric, underscore, dot, and hyphen allowed")

    existing = db.exec(select(Account).where(Account.session_name == data.session_name)).first()
    if existing:
        raise HTTPException(400, f"Account with session_name '{data.session_name}' already exists")

    account = Account(**data.model_dump())
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.delete("/accounts/{account_id}")
async def delete_account(account_id: int, db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(404, "Account not found")

    tasks = db.exec(select(Task).where(Task.account_id == account_id)).all()
    if tasks:
        raise HTTPException(400, f"Cannot delete account with {len(tasks)} associated tasks")

    db.delete(account)
    db.commit()
    return {"deleted": True}


@router.post("/scheduler/reload")
async def reload_scheduler():
    if not _scheduler:
        raise HTTPException(503, "Scheduler not available")
    await _scheduler.reload_all()
    return {"reloaded": True}


# ==================== Telegram 登录 API ====================

class SendCodeRequest(BaseModel):
    session_name: str
    phone_number: str


class SignInRequest(BaseModel):
    session_name: str
    phone_number: str
    code: str


class SignIn2FARequest(BaseModel):
    session_name: str
    password: str


@router.post("/auth/send-code")
async def send_code(data: SendCodeRequest):
    """发送 Telegram 验证码"""
    if not _telegram_manager:
        raise HTTPException(503, "Telegram manager not available")

    if not SESSION_NAME_PATTERN.match(data.session_name):
        raise HTTPException(400, "Invalid session_name")

    try:
        logger.info(f"Sending code to {data.phone_number} for session {data.session_name}")
        result = await _telegram_manager.send_code(data.session_name, data.phone_number)
        logger.info(f"Code sent successfully: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to send code: {e}\n{traceback.format_exc()}")
        raise HTTPException(400, f"Failed to send code: {str(e)}")


@router.post("/auth/sign-in")
async def sign_in(data: SignInRequest, db: Session = Depends(get_db)):
    """使用验证码登录"""
    if not _telegram_manager:
        raise HTTPException(503, "Telegram manager not available")

    try:
        result = await _telegram_manager.sign_in(data.session_name, data.phone_number, data.code)

        # 登录成功后自动创建账号
        if result.get("status") == "success":
            existing = db.exec(select(Account).where(Account.session_name == data.session_name)).first()
            if not existing:
                user_info = result.get("user", {})
                account_name = user_info.get("first_name") or user_info.get("username") or data.session_name
                account = Account(name=account_name, session_name=data.session_name)
                db.add(account)
                db.commit()
                db.refresh(account)
                result["account_id"] = account.id

        return result
    except Exception as e:
        raise HTTPException(400, f"Sign in failed: {str(e)}")


@router.post("/auth/sign-in-2fa")
async def sign_in_2fa(data: SignIn2FARequest, db: Session = Depends(get_db)):
    """使用两步验证密码登录"""
    if not _telegram_manager:
        raise HTTPException(503, "Telegram manager not available")

    try:
        result = await _telegram_manager.sign_in_2fa(data.session_name, data.password)

        # 登录成功后自动创建账号
        if result.get("status") == "success":
            existing = db.exec(select(Account).where(Account.session_name == data.session_name)).first()
            if not existing:
                user_info = result.get("user", {})
                account_name = user_info.get("first_name") or user_info.get("username") or data.session_name
                account = Account(name=account_name, session_name=data.session_name)
                db.add(account)
                db.commit()
                db.refresh(account)
                result["account_id"] = account.id

        return result
    except Exception as e:
        raise HTTPException(400, f"2FA sign in failed: {str(e)}")


@router.post("/auth/cancel")
async def cancel_login(session_name: str):
    """取消登录"""
    if not _telegram_manager:
        raise HTTPException(503, "Telegram manager not available")

    await _telegram_manager.cancel_login(session_name)
    return {"cancelled": True}
