"""Named menu destinations and compact persistent navigation."""

from enum import StrEnum

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


class Menu(StrEnum):
    """User-facing destinations with recognizable icons."""

    FRIDGE = "🧊 Мой холодильник"
    PURCHASES = "🛒 Добавить покупки"
    RECIPES = "🍳 Что приготовить"
    FAVORITES = "⭐ Избранное"
    PROFILE = "👤 Личный кабинет"
    HELP = "❓ Помощь"
    HOME = "🏠 В меню"


def keyboard() -> ReplyKeyboardMarkup:
    """Build a compact persistent menu with text accompanying every icon."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=item.value) for item in row]
            for row in (
                (Menu.PURCHASES, Menu.FRIDGE),
                (Menu.RECIPES, Menu.FAVORITES),
                (Menu.PROFILE, Menu.HELP),
                (Menu.HOME,),
            )
        ],
        resize_keyboard=True,
    )
