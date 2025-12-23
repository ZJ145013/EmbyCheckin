from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from loguru import logger

from .db import engine, create_db_and_tables, get_session
from .settings import settings
from .runner import TaskRunner
from .scheduler import SchedulerService
from .telegram import TelegramClientManager, ConversationRouter
from .web import api_router, ui_router
from .web.api import set_services


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting EmbyCheckin Scheduler...")

    create_db_and_tables(engine)
    logger.info(f"Database initialized: {settings.db_path}")

    telegram_manager = TelegramClientManager()
    conversation_router = ConversationRouter()

    runner = TaskRunner(
        settings=settings,
        session_factory=get_session,
        resources={
            "telegram_manager": telegram_manager,
            "conversation_router": conversation_router,
        },
    )

    scheduler = SchedulerService(runner=runner, session_factory=get_session)
    scheduler.start()

    set_services(scheduler, runner, telegram_manager)

    await scheduler.reload_all()
    logger.info("Scheduler started and tasks loaded")

    yield

    logger.info("Shutting down...")
    scheduler.shutdown()
    await telegram_manager.stop_all()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="EmbyCheckin Scheduler",
        version="2.0.0",
        lifespan=lifespan,
    )

    app.include_router(api_router)
    app.include_router(ui_router)

    static_dir = Path(__file__).parent / "web" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "embycheckin.app:app",
        host=settings.bind_host,
        port=settings.bind_port,
        reload=False,
    )
