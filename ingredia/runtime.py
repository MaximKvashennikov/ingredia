"""Compose provider and channel resources for the single-process photo trial."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from time import monotonic

import httpx
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from ingredia.accounts.retention import StockRetention
from ingredia.adapters.telegram import create_dispatcher
from ingredia.adapters.telegram_admin.router import create_admin_dispatcher
from ingredia.logging_config import get_logger
from ingredia.providers import create_recognizers
from ingredia.recipes.service import RecipeService
from ingredia.recognition.policy import TrialAdmission
from ingredia.recognition.service import PhotoTrial
from ingredia.settings import Settings
from ingredia.storage.database import create_database

logger = get_logger(__name__)


@dataclass(frozen=True)
class TrialRuntime:
    """Runtime state exposed to application health reporting."""

    polling_task: asyncio.Task[None]
    admin_task: asyncio.Task[None] | None = None
    retention_task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        """Report whether the local polling task is still active."""
        return not self.polling_task.done()


async def verify_bot(bot: Bot, expected_username: str) -> None:
    """Check credentials and refuse to replace an existing webhook."""
    identity = await bot.get_me()
    if identity.username != expected_username:
        raise RuntimeError("Telegram bot username does not match settings")
    if (await bot.get_webhook_info()).url:
        raise RuntimeError("An existing Telegram webhook prevents trial long polling")


async def stop_polling(task: asyncio.Task[None]) -> None:
    """Cancel polling and its serial handler before closing network clients."""
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    logger.info("Photo trial polling stopped")


async def stop_retention(task: asyncio.Task[None]) -> None:
    """Cancel maintenance before closing its database engine."""
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    logger.info("Expired stock maintenance stopped")


@asynccontextmanager
async def run_photo_trial(config: Settings) -> AsyncIterator[TrialRuntime]:
    """Own and close every trial resource in reverse construction order."""
    async with AsyncExitStack() as resources:
        client = await resources.enter_async_context(
            httpx.AsyncClient(follow_redirects=False, trust_env=False)
        )
        adapters = create_recognizers(config, client)
        bot = Bot(
            token=config.telegram.user.token.get_secret_value(),
            session=AiohttpSession(timeout=40),
        )
        resources.push_async_callback(bot.session.close)
        await verify_bot(bot, config.telegram.user.username)
        allowed = (
            None if config.telegram.trial.open_access else config.telegram.trial.allowed_user_ids
        )
        service = None
        recipes = None
        retention_task = None
        admission = TrialAdmission(allowed, 15, monotonic)
        if config.database.url is not None:
            engine, service = create_database(
                config.database.url.get_secret_value(),
                config.telegram.admin.user_ids,
            )
            resources.push_async_callback(engine.dispose)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            retention = StockRetention(sessions)
            await retention.run_once()
            retention_task = asyncio.create_task(retention.run_periodically())
            resources.push_async_callback(stop_retention, retention_task)
            recipes = RecipeService(
                sessions,
                adapters.recipes,
                TrialAdmission(allowed, 15, monotonic),
            )
        trial = PhotoTrial(
            adapters.photo, allowed, text_recognizer=adapters.text, admission=admission
        )
        dispatcher = (
            create_dispatcher(trial, service, recipes) if service else create_dispatcher(trial)
        )
        task = asyncio.create_task(
            dispatcher.start_polling(
                bot,
                handle_signals=False,
                close_bot_session=False,
                handle_as_tasks=False,
            )
        )
        resources.push_async_callback(stop_polling, task)
        logger.info(
            "Recognition started; provider=%s; open_access=%s",
            config.ai.provider,
            config.telegram.trial.open_access,
        )
        admin_task = None
        if service is not None and config.telegram.admin.token is not None:
            admin = Bot(
                token=config.telegram.admin.token.get_secret_value(),
                session=AiohttpSession(timeout=40),
            )
            resources.push_async_callback(admin.session.close)
            try:
                await verify_bot(admin, config.telegram.admin.username)
            except (TelegramAPIError, RuntimeError, OSError):
                logger.warning("Admin bot unavailable; user bot remains active")
            else:
                admin_dispatcher = create_admin_dispatcher(service, config.telegram.admin.user_ids)
                admin_task = asyncio.create_task(
                    admin_dispatcher.start_polling(
                        admin,
                        handle_signals=False,
                        close_bot_session=False,
                        handle_as_tasks=False,
                    )
                )
                resources.push_async_callback(stop_polling, admin_task)
        yield TrialRuntime(task, admin_task, retention_task)
