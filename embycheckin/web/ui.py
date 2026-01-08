from __future__ import annotations

from datetime import datetime
from pathlib import Path

from croniter import croniter
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pytz import timezone
from sqlmodel import Session, select

from ..db import get_session
from ..models import Account, Task, TaskRun
from ..tasks import list_task_types


def get_next_run_time(task: Task) -> str | None:
    """计算任务的下一次执行时间"""
    if not task.enabled or not task.schedule_cron:
        return None
    try:
        tz = timezone(task.timezone or "Asia/Shanghai")
        now = datetime.now(tz)
        cron = croniter(task.schedule_cron, now)
        next_time = cron.get_next(datetime)
        return next_time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def cron_to_chinese(cron_expr: str) -> str:
    """将 cron 表达式转换为中文描述"""
    try:
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            return cron_expr

        minute, hour, day, month, weekday = parts

        if cron_expr == "0 */6 * * *":
            return "每6小时"
        if cron_expr == "0 */12 * * *":
            return "每12小时"
        if minute.startswith("*/"):
            mins = minute[2:]
            return f"每{mins}分钟"
        if hour.startswith("*/"):
            hrs = hour[2:]
            return f"每{hrs}小时"

        if weekday != "*":
            if weekday == "1-5":
                weekday_desc = "工作日"
            elif weekday == "0" or weekday == "7":
                weekday_desc = "周日"
            elif weekday == "6":
                weekday_desc = "周六"
            else:
                weekday_desc = f"周{weekday}"
        else:
            weekday_desc = None

        if day == "*" and month == "*":
            if weekday_desc:
                if hour == "*":
                    return weekday_desc
                else:
                    return f"{weekday_desc} {hour}:{minute.zfill(2)}"
            else:
                if hour == "*" and minute == "*":
                    return "每分钟"
                elif hour == "*":
                    return f"每小时 {minute.zfill(2)}分"
                else:
                    return f"每天 {hour}:{minute.zfill(2)}"
        else:
            time_part = f"{hour}:{minute.zfill(2)}" if hour != "*" else "每小时"
            date_part = f"{month}月{day}日" if month != "*" and day != "*" else (
                f"每月{day}日" if day != "*" else f"{month}月"
            )
            return f"{date_part} {time_part}"
    except Exception:
        return cron_expr


router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals['cron_to_chinese'] = cron_to_chinese


def get_db():
    with get_session() as session:
        yield session


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    tasks = db.exec(select(Task).order_by(Task.id)).all()
    accounts = db.exec(select(Account)).all()
    recent_runs = db.exec(select(TaskRun).order_by(TaskRun.created_at.desc()).limit(10)).all()

    next_runs = {task.id: get_next_run_time(task) for task in tasks}

    last_runs = {}
    for task in tasks:
        last_run = db.exec(
            select(TaskRun)
            .where(TaskRun.task_id == task.id)
            .order_by(TaskRun.finished_at.desc())
            .limit(1)
        ).first()
        last_runs[task.id] = last_run

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "tasks": tasks,
        "accounts": accounts,
        "recent_runs": recent_runs,
        "task_types": list_task_types(),
        "next_runs": next_runs,
        "last_runs": last_runs,
    })


@router.get("/tasks/new", response_class=HTMLResponse)
def new_task(request: Request, db: Session = Depends(get_db)):
    accounts = db.exec(select(Account)).all()
    return templates.TemplateResponse("task_form.html", {
        "request": request,
        "task": None,
        "accounts": accounts,
        "task_types": list_task_types(),
    })


@router.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
def edit_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    accounts = db.exec(select(Account)).all()
    return templates.TemplateResponse("task_form.html", {
        "request": request,
        "task": task,
        "accounts": accounts,
        "task_types": list_task_types(),
    })


@router.get("/tasks/{task_id}/runs", response_class=HTMLResponse)
def task_runs(task_id: int, request: Request, db: Session = Depends(get_db)):
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
def all_logs(request: Request, db: Session = Depends(get_db)):
    runs = db.exec(select(TaskRun).order_by(TaskRun.created_at.desc()).limit(100)).all()
    return templates.TemplateResponse("logs.html", {
        "request": request,
        "task": None,
        "runs": runs,
    })


@router.get("/accounts", response_class=HTMLResponse)
def accounts_page(request: Request, db: Session = Depends(get_db)):
    accounts = db.exec(select(Account)).all()
    return templates.TemplateResponse("accounts.html", {
        "request": request,
        "accounts": accounts,
    })
