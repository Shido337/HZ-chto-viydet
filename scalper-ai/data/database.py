from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DB_PATH = os.getenv("DB_PATH", "./data/scalper.db")
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}", echo=False)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create all tables if they don't exist."""
    from data.models import Base  # noqa: WPS433

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
