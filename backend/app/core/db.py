from collections.abc import Generator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(path: str) -> Engine:
    database_url = path if path.startswith("sqlite:") else f"sqlite:///{path}"
    engine = create_engine(
        database_url,
        connect_args={"timeout": 5},
        pool_size=5,
        max_overflow=0,
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    return engine


@lru_cache
def get_engine() -> Engine:
    database_url = get_settings().sqlite_database_url
    if not database_url.startswith("sqlite:///"):
        raise RuntimeError("DATABASE_URL must be a local SQLite URL")
    database_path = Path(database_url[len("sqlite:///") :])
    database_path.parent.mkdir(parents=True, exist_ok=True)
    return make_engine(database_url)


def get_db() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session
