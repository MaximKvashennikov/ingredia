"""Enforce active accounts before user commands and costly photo processing."""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from ingredia.accounts.models import AccessDenied
from ingredia.accounts.service import AccountService


class AccountAccess(BaseMiddleware):
    """Register private identities and reject blocked users before handlers."""

    def __init__(self, service: AccountService) -> None:
        """Inject the authorization service."""
        self.service = service

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Authorize every message, including repeated buttons and photos."""
        if (
            not isinstance(event, Message)
            or event.chat.type != "private"
            or event.from_user is None
        ):
            return None
        try:
            await self.service.register(event.from_user.id, event.from_user.full_name)
            return await handler(event, data)
        except AccessDenied:
            await event.answer("Доступ к аккаунту заблокирован.")
            return None
