"""Small Telegram handlers coordinating the application service and typed views."""

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ErrorEvent, Message

from ingredia.accounts.service import AccountService
from ingredia.adapters.telegram.media import TelegramPhotoLoader
from ingredia.adapters.telegram.models import FailureReply, HelpText, PhotoJob, RecognitionReply
from ingredia.adapters.telegram.presenter import TelegramPresenter
from ingredia.logging_config import get_logger
from ingredia.recognition.errors import RecognitionFailure
from ingredia.recognition.service import PhotoTrial

logger = get_logger(__name__)


class PhotoHandlers:
    """Handle routed Telegram events without provider or prompt logic."""

    def __init__(self, trial: PhotoTrial, service: AccountService | None = None) -> None:
        """Inject the application-level photo trial."""
        self._trial = trial
        self._service = service

    @staticmethod
    async def identify(message: Message) -> None:
        """Show the caller's ID and the purpose of external photo processing."""
        if message.from_user is None:
            return
        await message.answer(
            f"Твой Telegram ID: {message.from_user.id}\n{HelpText.INTRODUCTION.value}"
        )

    async def recognize(self, message: Message, bot: Bot) -> None:
        """Process a photo once and present either its result or a safe error."""
        presenter = TelegramPresenter(message)
        try:
            await self._process_photo(message, bot, presenter)
        except RecognitionFailure as error:
            logger.info(
                "Photo recognition failed: %s; provider=%s", error.code, error.provider_code
            )
            await presenter.send_failure(FailureReply.from_failure(error))
        except TelegramAPIError:
            logger.warning("Telegram photo transfer or result delivery failed")

    async def _process_photo(
        self,
        message: Message,
        bot: Bot,
        presenter: TelegramPresenter,
    ) -> None:
        job = PhotoJob.from_message(message)
        loader = TelegramPhotoLoader(bot, message, job)
        result = await self._trial.process(job.user_id, job.message_id, loader)
        if self._service is not None:
            await self._service.profile(job.user_id)
        await presenter.send_result(RecognitionReply.from_result(result, job.message_id))
        logger.info("Photo recognition completed: products=%d", len(result.products))

    @staticmethod
    async def unsupported(message: Message) -> None:
        """Explain the supported input without changing user data."""
        await message.answer(HelpText.UNSUPPORTED.value)

    @staticmethod
    async def unexpected(event: ErrorEvent) -> bool:
        """Record an exception class without serializing the private update or traceback."""
        logger.error("Telegram handler failed: %s", type(event.exception).__name__)
        return True
