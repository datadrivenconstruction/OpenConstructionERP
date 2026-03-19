"""Database engine, session, and base model.

Supports both PostgreSQL (production) and SQLite (local dev without Docker).
Set DATABASE_URL to 'sqlite+aiosqlite:///./openestimate.db' for SQLite mode.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime

from sqlalchemy import DateTime, MetaData, String, TypeDecorator, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import get_settings

# Naming convention for auto-generated constraint names
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class GUID(TypeDecorator):
    """Platform-independent UUID type.

    Uses PostgreSQL UUID when available, otherwise stores as String(36).
    This allows the same models to work with both PostgreSQL and SQLite.
    """

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value: uuid.UUID | str | None, dialect: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return str(value)
        return value

    def process_result_value(self, value: str | None, dialect: object) -> uuid.UUID | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(value)


class Base(DeclarativeBase):
    """Base class for all ORM models.

    Provides: id (UUID PK), created_at, updated_at.
    Table naming: set __tablename__ explicitly as 'oe_{module}_{entity}'.
    """

    metadata = MetaData(naming_convention=convention)

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def _is_sqlite(url: str) -> bool:
    return "sqlite" in url


def create_engine_from_settings():
    """Create async engine from application settings."""
    settings = get_settings()
    url = settings.database_url

    kwargs: dict = {
        "echo": settings.database_echo,
        "future": True,
    }

    if _is_sqlite(url):
        # SQLite doesn't support pool_size/max_overflow
        # Enable WAL mode for concurrent reads during writes
        from sqlalchemy import event as sa_event
        from sqlalchemy.engine import Engine

        @sa_event.listens_for(Engine, "connect")
        def _set_sqlite_pragma(dbapi_conn: object, _: object) -> None:
            cursor = dbapi_conn.cursor()  # type: ignore[union-attr]
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_size"] = settings.database_pool_size
        kwargs["max_overflow"] = settings.database_max_overflow

    return create_async_engine(url, **kwargs)


engine = create_engine_from_settings()
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency: yields an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
