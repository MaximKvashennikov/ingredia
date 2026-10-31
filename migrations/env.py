"""Run schema migrations using the configured asynchronous engine."""

import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from ingredia.settings import get_settings
from ingredia.storage.models import Base


def apply(connection: Connection) -> None:
    """Apply versioned revisions within a migration context."""
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def migrate() -> None:
    """Dispose migration resources even after a failed revision."""
    config = get_settings()
    if config.database.url is None:
        raise RuntimeError("DATABASE__URL is required")
    engine = create_async_engine(config.database.url.get_secret_value(), hide_parameters=True)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(apply)
    finally:
        await engine.dispose()


asyncio.run(migrate())
