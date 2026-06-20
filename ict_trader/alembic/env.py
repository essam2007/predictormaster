"""Alembic environment.

Run ``alembic revision --autogenerate -m "..."`` then ``alembic upgrade head``. The
pre-live migration converts ``bars``/``ticks`` to TimescaleDB hypertables; until then the
ORM ``create_all`` (used by the API on startup) is sufficient for SQLite.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from ict_trader.store.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Prefer the runtime DSN; strip the async driver for Alembic's sync engine.
_url = os.environ.get("ICT_TRADER_DB_URL", "sqlite:///./ict_trader.db")
config.set_main_option("sqlalchemy.url", _url.replace("+aiosqlite", "").replace("+asyncpg", ""))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"),
                      target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
