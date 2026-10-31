"""Bounded Telegram photo loading independent of recognition decisions."""

from dataclasses import dataclass

from aiogram import Bot
from aiogram.types import Message

from ingredia.adapters.telegram.models import HelpText, PhotoJob
from ingredia.recognition.errors import FailureCode, RecognitionFailure
from ingredia.recognition.media import MAX_INPUT_BYTES, BoundedPhotoBuffer


@dataclass
class TelegramPhotoLoader:
    """An awaitable download operation invoked only after trial admission."""

    bot: Bot
    message: Message
    job: PhotoJob

    async def __call__(self) -> bytes:
        """Download one bounded photo to memory without exposing its URL to Z.ai."""
        if self.job.file_size is not None and self.job.file_size > MAX_INPUT_BYTES:
            raise RecognitionFailure(FailureCode.INVALID_IMAGE)
        await self.message.answer(HelpText.PROGRESS.value)
        with BoundedPhotoBuffer() as destination:
            await self.bot.download(self.job.file_id, destination=destination, timeout=15)
            return destination.getvalue()
