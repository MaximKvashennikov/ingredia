"""Shared transactional owner authorization for private application services."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ingredia.accounts.models import AccessDenied
from ingredia.storage.models import Account


async def active_account(session: AsyncSession, telegram_id: int) -> Account:
    """Lock and verify the actor before reading or changing private persistent data."""
    account = await session.scalar(
        select(Account).where(Account.telegram_id == telegram_id).with_for_update()
    )
    if account is None or account.blocked:
        raise AccessDenied
    return account
