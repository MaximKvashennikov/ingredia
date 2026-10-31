"""Delete long-expired stock while preserving minimal event deduplication keys."""

import asyncio
from collections.abc import Callable
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ingredia.clock import current_date
from ingredia.logging_config import get_logger
from ingredia.storage.models import Account, Batch, RemovedStockEvent

RETENTION_DAYS = 30
BATCH_SIZE = 500
logger = get_logger(__name__)


async def purge_owner(session: AsyncSession, owner_id: str, today: date) -> int:
    """Remove expired rows atomically; callers hold the corresponding account lock."""
    cutoff = today - timedelta(days=RETENTION_DAYS)
    removed = 0
    while True:
        keys = list(
            await session.scalars(
                select(Batch.event_key)
                .where(
                    Batch.owner_id == owner_id,
                    Batch.expiry < cutoff,
                )
                .order_by(Batch.id)
                .limit(BATCH_SIZE)
                .with_for_update()
            )
        )
        if not keys:
            return removed
        session.add_all(RemovedStockEvent(event_key=key) for key in keys)
        await session.flush()
        await session.execute(
            delete(Batch).where(Batch.owner_id == owner_id, Batch.event_key.in_(keys))
        )
        removed += len(keys)


class StockRetention:
    """Run system maintenance separately from user or administrator permissions."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        today: Callable[[], date] = current_date,
    ) -> None:
        """Inject the same persistence boundary and calendar used by stock reads."""
        self._sessions = sessions
        self._today = today

    async def run_once(self) -> int:
        """Clean every eligible owner, releasing database locks between owners."""
        today = self._today()
        cutoff = today - timedelta(days=RETENTION_DAYS)
        removed = 0
        while True:
            async with self._sessions() as session:
                owners = list(
                    await session.scalars(
                        select(Batch.owner_id)
                        .where(Batch.expiry < cutoff)
                        .distinct()
                        .order_by(Batch.owner_id)
                        .limit(100)
                    )
                )
            if not owners:
                break
            for owner_id in owners:
                async with self._sessions.begin() as session:
                    await session.scalar(
                        select(Account).where(Account.id == owner_id).with_for_update()
                    )
                    removed += await purge_owner(session, owner_id, today)
        if removed:
            logger.info("Expired stock cleanup completed: removed=%d", removed)
        return removed

    async def run_periodically(self, interval_seconds: float = 3600) -> None:
        """Repeat hourly; log only error classes and recover after transient database failures."""
        if interval_seconds <= 0:
            raise ValueError("A positive cleanup interval is required")
        delay = interval_seconds
        while True:
            await asyncio.sleep(delay)
            try:
                await self.run_once()
            except SQLAlchemyError as error:
                logger.error("Expired stock cleanup failed: category=%s", type(error).__name__)
                delay = min(60, interval_seconds)
            else:
                delay = interval_seconds
