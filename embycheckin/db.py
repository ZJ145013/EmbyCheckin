from __future__ import annotations

from pathlib import Path
from typing import Callable

from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.engine import Engine

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


def get_session_factory(engine: Engine) -> Callable[[], Session]:
    return lambda: Session(engine)


engine = make_engine()
get_session = get_session_factory(engine)
