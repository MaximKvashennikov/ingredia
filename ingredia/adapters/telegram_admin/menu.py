"""Administrative menu labels and persistent keyboard."""

from enum import StrEnum

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


class AdminMenu(StrEnum):
    """Readable destinations with text accompanying every icon."""

    USERS = "👥 Пользователи"
    SEARCH = "🔎 Найти пользователя"
    BLOCKED = "🔴 Заблокированные"
    HELP = "ℹ️ Помощь"
    HOME = "🏠 Главное меню"
    BACK = "⬅️ Назад"


def admin_keyboard() -> ReplyKeyboardMarkup:
    """Build navigation that never requires copying internal account IDs."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=item.value) for item in row]
            for row in (
                (AdminMenu.USERS, AdminMenu.SEARCH),
                (AdminMenu.BLOCKED, AdminMenu.HELP),
                (AdminMenu.BACK, AdminMenu.HOME),
            )
        ],
        resize_keyboard=True,
    )
