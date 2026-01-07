from __future__ import annotations

from pathlib import Path
from typing import Callable

from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy import text
from loguru import logger

from .settings import settings


def make_engine(db_url: str | None = None) -> Engine:
    url = db_url or settings.database_url
    if url.startswith("sqlite:///"):
        db_file = url.removeprefix("sqlite:///")
        Path(db_file).parent.mkdir(parents=True, exist_ok=True)

    return create_engine(
        url,
        echo=False,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
    )


def create_db_and_tables(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
    _migrate_nullable_columns(engine)


def _migrate_nullable_columns(engine: Engine) -> None:
    """Migrate task table to allow NULL for account_id and target columns."""
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(task)")).fetchall()
        columns = {row[1]: row[3] for row in result}  # name -> notnull

        if columns.get("account_id") == 1 or columns.get("target") == 1:
            logger.info("Migrating task table to allow NULL for account_id and target")
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS task_new (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR NOT NULL,
                    type VARCHAR NOT NULL,
                    enabled INTEGER NOT NULL,
                    account_id INTEGER,
                    target VARCHAR,
                    schedule_cron VARCHAR NOT NULL,
                    timezone VARCHAR NOT NULL,
                    jitter_seconds INTEGER NOT NULL,
                    max_runtime_seconds INTEGER NOT NULL,
                    retries INTEGER NOT NULL,
                    retry_backoff_seconds INTEGER NOT NULL,
                    params JSON,
                    created_at DATETIME,
                    updated_at DATETIME,
                    FOREIGN KEY(account_id) REFERENCES account(id)
                )
            """))
            conn.execute(text("""
                INSERT INTO task_new SELECT * FROM task
            """))
            conn.execute(text("DROP TABLE task"))
            conn.execute(text("ALTER TABLE task_new RENAME TO task"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_task_account_id ON task(account_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_task_target ON task(target)"))
            conn.commit()
            logger.info("Migration completed")


def get_session_factory(engine: Engine) -> Callable[[], Session]:
    return lambda: Session(engine)


engine = make_engine()
get_session = get_session_factory(engine)
