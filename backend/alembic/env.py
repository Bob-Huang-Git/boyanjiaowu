from logging.config import fileConfig
from pathlib import Path

from alembic import context
from app.core import models  # noqa: F401
from app.core.config import get_settings
from app.core.db import Base, make_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_online() -> None:
    database_url = get_settings().sqlite_database_url
    if not database_url.startswith("sqlite:///"):
        raise RuntimeError("DATABASE_URL must be a local SQLite URL")
    Path(database_url[len("sqlite:///") :]).parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(database_url)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
