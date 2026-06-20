"""Async SQLAlchemy engine/session factory.

SQLite (aiosqlite) for the MVP; switch ``db_url`` to ``postgresql+asyncpg://...`` for the
TimescaleDB target with no app-code change (all access goes through repositories).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self.engine = create_async_engine(url, future=True)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_all(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as s:
            yield s

    async def dispose(self) -> None:
        await self.engine.dispose()
