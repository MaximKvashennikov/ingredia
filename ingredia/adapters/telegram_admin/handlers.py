"""Minimal administrative directory and confirmed access changes."""

from html import escape
from time import monotonic
from uuid import uuid4

from aiogram import Bot
from aiogram.types import (
    CallbackQuery,
    ErrorEvent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from ingredia.accounts.models import AccessDenied, AccountView, Conflict
from ingredia.accounts.service import AccountService
from ingredia.adapters.telegram_admin.models import StatusConfirmation
from ingredia.logging_config import get_logger


class AdminHandlers:
    """Keep transient confirmations out of user routes and callback payloads."""

    def __init__(self, service: AccountService, allowed: frozenset[int]) -> None:
        """Inject trusted identities; an empty set denies all administrative access."""
        self.service = service
        self.allowed = allowed
        self.pending: dict[int, tuple[str, StatusConfirmation]] = {}

    async def prepare(self, message: Message) -> None:
        """Authorize and snapshot a target version before asking for confirmation."""
        if message.from_user is None or message.from_user.id not in self.allowed:
            await message.answer("Доступ запрещён.")
            return
        actor = message.from_user.id
        try:
            await self.service.admin_profile(actor)
            command, target, reason = (message.text or "").split(maxsplit=2)
            if not reason.strip() or len(reason) > 200:
                raise ValueError
            target_view = await self.service.admin_target(actor, target)
        except (ValueError, AccessDenied):
            await message.answer("Нет доступа или неверный формат. /block ID причина")
            return
        await self.ask_confirmation(
            message,
            target_view,
            command.split("@")[0] == "/block",
            reason,
        )

    async def ask_confirmation(
        self,
        message: Message,
        target: AccountView,
        blocked: bool,
        reason: str,
    ) -> None:
        """Share one actor-bound confirmation path between menu and legacy commands."""
        if message.from_user is None:
            return
        actor = message.from_user.id
        await self.service.admin_profile(actor)
        if target.telegram_id in self.allowed:
            raise AccessDenied
        if not reason.strip() or len(reason) > 200:
            raise ValueError("Invalid administrative reason")
        token = uuid4().hex
        intent = StatusConfirmation(
            actor,
            target.id,
            target.version,
            blocked,
            reason.strip(),
            monotonic() + 300,
            target.name,
        )
        self.pending[actor] = (token, intent)
        action = "🔒 Заблокировать" if blocked else "🔓 Разблокировать"
        await message.answer(
            f"{action} <b>{escape(target.name)}</b>?\n\n"
            f"Причина: {escape(intent.reason)}\n\n"
            "Изменение произойдёт только после подтверждения.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text=action, callback_data=f"status:{token}"),
                        InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel:{token}"),
                    ]
                ]
            ),
        )

    async def confirm(self, callback: CallbackQuery, bot: Bot) -> None:
        """Check identity and access again; old buttons cannot replay an action."""
        actor = callback.from_user.id
        saved = self.pending.get(actor)
        token = (callback.data or "").partition(":")[2]
        if actor not in self.allowed or saved is None or saved[0] != token:
            await callback.answer("Недоступное или устаревшее действие.", show_alert=True)
            return
        intent = saved[1]
        self.pending.pop(actor)
        if intent.expired:
            await callback.answer("Подтверждение истекло.", show_alert=True)
            return
        try:
            await self.service.admin_profile(actor)
            if (callback.data or "").startswith("cancel:"):
                await callback.answer("Отменено.")
                await self.result(
                    bot, actor, "↩️ Действие отменено.\nСтатус пользователя не изменился."
                )
                return
            await self.service.change_status(
                actor,
                intent.target,
                intent.version,
                intent.blocked,
                intent.reason,
            )
        except (AccessDenied, Conflict):
            await callback.answer(
                "Нет доступа или карточка изменилась. Обновите список.", show_alert=True
            )
            return
        await callback.answer("Статус сохранён.")
        status = "заблокирован" if intent.blocked else "разблокирован"
        await self.result(bot, actor, f"✅ {intent.target_name} — {status}.")

    @staticmethod
    async def result(bot: Bot, actor: int, text: str) -> None:
        """Offer a direct return after a completed or cancelled operation."""
        await bot.send_message(
            actor,
            text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="⬅️ К списку", callback_data="alist"),
                        InlineKeyboardButton(text="🏠 В меню", callback_data="ahome"),
                    ]
                ]
            ),
        )

    @staticmethod
    async def unexpected(event: ErrorEvent) -> bool:
        """Log only the exception category, never the administrative update."""
        get_logger(__name__).error("Admin handler failed: %s", type(event.exception).__name__)
        return True
