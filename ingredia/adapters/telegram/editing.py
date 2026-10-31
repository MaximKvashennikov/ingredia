"""Update button-driven screens without accumulating repeated list messages."""

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup


async def replace_screen(
    callback: CallbackQuery,
    bot: Bot,
    text: str,
    markup: InlineKeyboardMarkup,
) -> None:
    """Edit the originating private screen and tolerate an unchanged refresh."""
    if callback.message is None:
        return
    try:
        await bot.edit_message_text(
            text=text,
            chat_id=callback.from_user.id,
            message_id=callback.message.message_id,
            parse_mode="HTML",
            reply_markup=markup,
        )
    except TelegramBadRequest as error:
        if "message is not modified" in error.message:
            return
        raise
