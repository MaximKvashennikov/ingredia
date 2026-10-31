"""Typed Telegram jobs, message texts and response representations."""

from enum import StrEnum

from aiogram.types import Message
from pydantic import BaseModel, Field

from ingredia.recognition.errors import FailureCode, RecognitionFailure
from ingredia.recognition.models import PhotoRecognition


class HelpText(StrEnum):
    """Reusable user-facing messages independent of handler control flow."""

    INTRODUCTION = (
        "Фото и текст продуктов обрабатываются внешней облачной моделью.\n"
        "Присылай только данные о продуктах. Проверяй названия, количества и сроки: "
        "распознавание может ошибаться."
    )
    PROGRESS = "Фото принято. Распознаю продукты через облачную модель…"
    UNSUPPORTED = (
        "Сейчас проверяем только фото. Отправь одну фотографию продуктов; "
        "для своего Telegram ID используй /id."
    )


class ErrorText(StrEnum):
    """Localize each named application failure without a loose message dictionary."""

    FORBIDDEN = "Пробный доступ закрыт. Отправь /id и передай свой ID владельцу проекта."
    DUPLICATE = "Этот ввод уже обрабатывался. Повторный вызов модели не сделан."
    BUSY = "Сейчас обрабатываю другой список продуктов. Попробуй немного позже."
    COOLDOWN = "Подожди 15 секунд между запросами распознавания."
    INVALID_IMAGE = "Нужна корректная фотография JPEG/PNG до 5 МБ, не более 20 млн пикселей."
    TIMEOUT = "Распознавание не завершилось вовремя. Можно отправить фото позже."
    UNAVAILABLE = "Сервис распознавания сейчас недоступен. Попробуй позже."
    PROVIDER_BUSY = "Сервис распознавания сообщает о временной перегрузке модели. Попробуй позже."
    BILLING = "Сервис распознавания не предоставил бесплатный доступ для этого запроса. Платный режим не включён."
    CREDENTIALS = "Сервис распознавания отклонил доступ. Нужно проверить ключ и права аккаунта."
    QUOTA = "Сервис распознавания ограничил запросы или исчерпана квота. Платного переключения нет."
    INVALID_RESPONSE = "Не удалось получить корректный список продуктов. Данные не сохранены."
    MODEL_UNAVAILABLE = (
        "Сервис распознавания отклонил запрос к выбранной модели. Нужно проверить её доступность."
    )


class FailureReply(BaseModel):
    """A validated error presentation containing only a known text and numeric code."""

    message: ErrorText
    provider_code: str | None = Field(default=None, pattern=r"^[0-9]{1,10}$")

    @classmethod
    def from_failure(cls, error: RecognitionFailure) -> "FailureReply":
        """Resolve the localized enum member matching the typed failure name."""
        return cls(message=ErrorText[error.code.name], provider_code=error.provider_code)

    def render(self) -> str:
        """Render an error without provider bodies, URLs or secret values."""
        suffix = f" Код Z.ai: {self.provider_code}." if self.provider_code else ""
        return self.message.value + suffix


class PhotoJob(BaseModel):
    """Required Telegram identifiers for one photo download."""

    user_id: int
    message_id: int
    file_id: str = Field(repr=False)
    file_size: int | None

    @classmethod
    def from_message(cls, message: Message) -> "PhotoJob":
        """Extract a photo job after routing has selected a private photo message."""
        media = message.photo[-1] if message.photo else message.document
        if message.from_user is None or media is None:
            raise RecognitionFailure(FailureCode.INVALID_IMAGE)
        return cls(
            user_id=message.from_user.id,
            message_id=message.message_id,
            file_id=media.file_id,
            file_size=media.file_size,
        )


class RecognitionReply(BaseModel):
    """A document and an optional compact text preview for Telegram."""

    filename: str
    json_text: str = Field(repr=False)
    caption: str

    @classmethod
    def from_result(cls, result: PhotoRecognition, message_id: int) -> "RecognitionReply":
        """Format the validated domain result without changing inventory."""
        unclear = sum(product.needs_clarification for product in result.products)
        return cls(
            filename=f"recognition-{message_id}.json",
            json_text=result.model_dump_json(indent=2),
            caption=(
                f"Продуктов: {len(result.products)}. Требуют уточнения: {unclear}.\n"
                "GLM-4.6V-Flash · результат проверен по Pydantic-схеме.\n"
                "Это наблюдения модели, а не подтверждение свежести. В БД ничего не записано."
            ),
        )

    @property
    def document(self) -> bytes:
        """Encode the result as an in-memory UTF-8 document."""
        return self.json_text.encode("utf-8")

    @property
    def preview(self) -> str | None:
        """Keep text replies below Telegram's message limit."""
        return self.json_text if len(self.document) <= 3300 else None
