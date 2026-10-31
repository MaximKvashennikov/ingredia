"""Central authorization for every administrative message and callback."""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from ingredia.accounts.models import AccessDenied
from ingredia.accounts.service import AccountService


class AdminAccess(BaseMiddleware):
    """Reject non-private or untrusted events before exposing navigation or FSM steps."""

    def __init__(self, service: AccountService, allowed: frozenset[int]) -> None:
        """Inject server-controlled administrative identities."""
        self.service = service
        self.allowed = allowed

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Recheck the current account on every command, button and text answer."""
        if not isinstance(event, Message | CallbackQuery):
            return None
        chat = event if isinstance(event, Message) else event.message
        if chat is None or chat.chat.type != "private":
            return None
        sender = event.from_user
        try:
            if sender is None or sender.id not in self.allowed:
                raise AccessDenied
            await self.service.register(sender.id, sender.full_name)
            await self.service.admin_profile(sender.id)
            return await handler(event, data)
        except AccessDenied:
            if isinstance(event, CallbackQuery):
                await event.answer("Доступ запрещён.", show_alert=True)
                return None
            await event.answer("Доступ запрещён.")
            return None
