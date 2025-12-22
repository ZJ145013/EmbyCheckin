from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from ..db import get_session
from ..models import Account, Task, TaskRun
from ..tasks import list_task_types


router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def get_db():
    with get_session() as session:
        yield session


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    tasks = db.exec(select(Task).order_by(Task.id)).all()
    accounts = db.exec(select(Account)).all()
    recent_runs = db.exec(select(TaskRun).order_by(TaskRun.created_at.desc()).limit(10)).all()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "tasks": tasks,
        "accounts": accounts,
        "recent_runs": recent_runs,
        "task_types": list_task_types(),
    })


@router.get("/tasks/new", response_class=HTMLResponse)
async def new_task(request: Request, db: Session = Depends(get_db)):
    accounts = db.exec(select(Account)).all()
    return templates.TemplateResponse("task_form.html", {
        "request": request,
        "task": None,
        "accounts": accounts,
        "task_types": list_task_types(),
    })


@router.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
async def edit_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    accounts = db.exec(select(Account)).all()
    return templates.TemplateResponse("task_form.html", {
        "request": request,
        "task": task,
        "accounts": accounts,
        "task_types": list_task_types(),
    })


@router.get("/tasks/{task_id}/runs", response_class=HTMLResponse)
async def task_runs(task_id: int, request: Request, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    runs = db.exec(
        select(TaskRun)
        .where(TaskRun.task_id == task_id)
        .order_by(TaskRun.created_at.desc())
        .limit(50)
    ).all()
    return templates.TemplateResponse("logs.html", {
        "request": request,
        "task": task,
        "runs": runs,
    })


@router.get("/logs", response_class=HTMLResponse)
async def all_logs(request: Request, db: Session = Depends(get_db)):
    runs = db.exec(select(TaskRun).order_by(TaskRun.created_at.desc()).limit(100)).all()
    return templates.TemplateResponse("logs.html", {
        "request": request,
        "task": None,
        "runs": runs,
    })


@router.get("/accounts", response_class=HTMLResponse)
async def accounts_page(request: Request, db: Session = Depends(get_db)):
    accounts = db.exec(select(Account)).all()
    return templates.TemplateResponse("accounts.html", {
        "request": request,
        "accounts": accounts,
    })
