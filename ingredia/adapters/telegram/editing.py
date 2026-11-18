"""Обновление экранов Telegram без накопления повторных сообщений."""

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InputRichMessage


async def replace_screen(
    callback: CallbackQuery,
    bot: Bot,
    text: str | InputRichMessage,
    markup: InlineKeyboardMarkup,
) -> None:
    """Обновить исходное сообщение и пропустить ошибку неизменённого содержимого.

    Args:
        callback: Нажатие кнопки с исходным сообщением; при его отсутствии обновление пропускается.
        bot: Клиент Telegram для редактирования сообщения в личном чате отправителя.
        text: Новый HTML-текст или структурированное rich-сообщение.
        markup: Клавиатура, которая заменяет прежние кнопки экрана.

    Raises:
        TelegramBadRequest: Telegram отклонил запрос по причине, отличной от неизменённого сообщения.
    """
    if callback.message is None:
        return
    try:
        await bot.edit_message_text(
            text=text if isinstance(text, str) else None,
            rich_message=text if isinstance(text, InputRichMessage) else None,
            chat_id=callback.from_user.id,
            message_id=callback.message.message_id,
            parse_mode="HTML" if isinstance(text, str) else None,
            reply_markup=markup,
        )
    except TelegramBadRequest as error:
        if "message is not modified" in error.message:
            return
        raise
