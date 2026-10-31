"""Send already formatted views without re-running recognition."""

from dataclasses import dataclass

from aiogram.types import BufferedInputFile, Message

from ingredia.adapters.telegram.models import FailureReply, RecognitionReply


@dataclass
class TelegramPresenter:
    """Deliver typed views through one Telegram message context."""

    message: Message

    async def send_result(self, reply: RecognitionReply) -> None:
        """Send a JSON file and a preview when the result fits a short message."""
        await self.message.answer_document(
            BufferedInputFile(reply.document, filename=reply.filename),
            caption=reply.caption,
        )
        if reply.preview is not None:
            await self.message.answer(reply.preview, parse_mode=None)

    async def send_failure(self, reply: FailureReply) -> None:
        """Send only the safe localized representation of a failure."""
        await self.message.answer(reply.render())
