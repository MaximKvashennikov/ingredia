"""Однократное заполнение неизвестных сроков без замены явных дат и отказов от оценки."""

from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ingredia.accounts.expiry import estimate_name
from ingredia.storage.models import Batch


async def fill_missing_expiry(session: AsyncSession, owner_id: str, today: date) -> None:
    """Заполнить применимые оценки и убрать прежние искусственные даты проверки.

    Вызывающая сторона должна удерживать блокировку аккаунта владельца.
    Изменения отправляются в БД через flush; завершение транзакции остаётся за вызывающим кодом.

    Args:
        session: Сессия текущей транзакции с удерживаемой блокировкой владельца.
        owner_id: Внутренний ID аккаунта, чьи партии требуется дополнить.
        today: Текущая календарная дата для партий с неизвестной датой покупки.
    """
    rows = await session.scalars(
        select(Batch).where(
            Batch.owner_id == owner_id,
            or_(
                Batch.expiry_source == "review",
                Batch.expiry.is_(None) & (Batch.expiry_source == "unknown"),
            ),
        )
    )
    for row in rows:
        estimate = estimate_name(row.name, row.added_on or today, unknown_age=row.added_on is None)
        row.expiry = estimate.expiry if estimate else None
        row.expiry_source = "estimated" if estimate else "unavailable"
        row.expiry_estimate = estimate.model_dump(mode="json") if estimate else None
        row.version += 1
    await session.flush()
