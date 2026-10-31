"""Photo-first grocery drafts with human-readable confirmation cards."""

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from pydantic import ValidationError

from ingredia.accounts.models import AccessDenied, Conflict
from ingredia.accounts.service import AccountService
from ingredia.adapters.telegram.media import TelegramPhotoLoader
from ingredia.adapters.telegram.models import FailureReply, PhotoJob
from ingredia.adapters.telegram.views import candidate_card
from ingredia.logging_config import get_logger
from ingredia.recognition.errors import RecognitionFailure
from ingredia.recognition.models import PhotoRecognition
from ingredia.recognition.service import PhotoTrial

logger = get_logger(__name__)


class PurchaseHandlers:
    """Coordinate extraction and a durable explicit inventory decision."""

    def __init__(self, trial: PhotoTrial, service: AccountService) -> None:
        """Inject cloud-independent extraction and transactional persistence."""
        self.trial = trial
        self.service = service

    async def photo(self, message: Message, bot: Bot) -> None:
        """Create a purchase preview from a photo without a JSON document."""
        job = PhotoJob.from_message(message)
        logger.info(
            "Photo purchase received: event=%d bytes=%s transport=%s",
            job.message_id,
            job.file_size,
            "photo" if message.photo else "document",
        )
        try:
            result = await self.trial.process(
                job.user_id,
                job.message_id,
                TelegramPhotoLoader(bot, message, job),
            )
            await self.present(message, result)
        except RecognitionFailure as error:
            logger.warning("Purchase recognition failed: input=photo category=%s", error.code.value)
            await message.answer(
                "Не удалось распознать фото.\n" + FailureReply.from_failure(error).render()
            )

    async def text(self, message: Message) -> None:
        """Accept natural grocery text without imposing command syntax."""
        if message.from_user is None:
            return
        await message.answer("✍️ Разбираю список покупок…")
        try:
            result = await self.trial.process_text(
                message.from_user.id,
                message.message_id,
                message.text or "",
            )
            await self.present(message, result)
        except RecognitionFailure as error:
            logger.warning("Purchase recognition failed: input=text category=%s", error.code.value)
            await message.answer(
                "Не удалось разобрать список.\n" + FailureReply.from_failure(error).render()
            )

    async def present(self, message: Message, result: PhotoRecognition) -> None:
        """Show bounded cards and confirmation only for an unambiguous candidate list."""
        if message.from_user is None:
            return
        logger.info(
            "Purchase recognition result: products=%d warnings=%d",
            len(result.products),
            len(result.warnings),
        )
        if not result.products:
            await message.answer(
                "🔎 Продукты не найдены.\nПришлите другое фото или перечислите покупки текстом."
            )
            return
        try:
            preview = await self.service.preview_purchase(
                message.from_user.id,
                f"telegram:{message.message_id}",
                result,
            )
        except Conflict:
            await message.answer(
                "Список уже обработан. Откройте холодильник или пришлите новые покупки."
            )
            return
        await message.answer(
            "🛒 <b>Проверьте покупки</b>\n\nПока ничего не добавлено.", parse_mode="HTML"
        )
        result = preview.result
        has_estimates = any(preview.estimates)
        if has_estimates:
            await message.answer(
                "📅 Даты «по оценке» рассчитаны от сегодняшней покупки при хранении ≤4 °C. "
                "Это ориентир, не срок с упаковки. Если условия другие, добавьте без оценок."
            )
        for offset in range(0, len(result.products), 4):
            cards = [
                candidate_card(
                    item,
                    i + 1,
                    preview.estimates[i] if i < len(preview.estimates) else None,
                )
                for i, item in enumerate(result.products)
            ][offset : offset + 4]
            await message.answer("\n\n".join(cards), parse_mode="HTML")
        for warning in result.warnings:
            await message.answer("ℹ️ " + warning, parse_mode=None)
        buttons = []
        if not any(item.needs_clarification for item in result.products):
            buttons.append(
                InlineKeyboardButton(
                    text="✅ Добавить в холодильник", callback_data=f"buy:{preview.id}"
                )
            )
        buttons.append(InlineKeyboardButton(text="❌ Отмена", callback_data=f"drop:{preview.id}"))
        ready = not any(item.needs_clarification for item in result.products)
        if ready and has_estimates:
            buttons.append(
                InlineKeyboardButton(
                    text="📅 Добавить без оценочных дат",
                    callback_data=f"plain:{preview.id}",
                )
            )
        await message.answer(
            "Всё верно? Подтвердите добавление.\nЧтобы исправить список, напишите его целиком новым сообщением."
            if ready
            else "Нужно уточнение. Напишите полный список с исправлениями — я покажу новый вариант.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[button] for button in buttons]),
        )

    async def decide(self, callback: CallbackQuery, bot: Bot) -> None:
        """Recheck ownership and status on every callback; never save a preview twice."""
        action, _, identifier = (callback.data or "").partition(":")
        try:
            count = await self.service.decide_purchase(
                callback.from_user.id,
                identifier,
                action in {"buy", "plain"},
                use_estimates=action != "plain",
            )
        except (AccessDenied, Conflict):
            await callback.answer("Список недоступен или уже обработан.", show_alert=True)
            return
        except ValidationError:
            get_logger(__name__).warning("Purchase confirmation failed validation")
            await callback.answer(
                "Проверьте количества и пришлите исправленный список.", show_alert=True
            )
            return
        await callback.answer("Добавлено" if count else "Отменено")
        await bot.send_message(
            callback.from_user.id,
            f"✅ <b>Покупки добавлены</b>\n\nПозиций: {count}\nОткройте «🧊 Мой холодильник»."
            if count
            else "❌ Добавление отменено.\nПродукты не изменены.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🍳 Подобрать рецепты", callback_data="recipes:new"
                        ),
                        InlineKeyboardButton(text="🧊 Холодильник", callback_data="fridge:0"),
                    ]
                ]
            )
            if count
            else None,
        )
