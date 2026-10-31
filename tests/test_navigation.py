"""Telegram navigation and administrative authorization through fake transport."""

import asyncio
from datetime import UTC, datetime

from aiogram import Bot
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from test_accounts import database
from test_telegram import FakeRecognizer, FakeSession

from ingredia.adapters.telegram import create_dispatcher
from ingredia.adapters.telegram_admin.router import create_admin_dispatcher
from ingredia.recognition.service import PhotoTrial


class Session(FakeSession):
    """Capture messages and callback acknowledgments without Telegram requests."""

    async def make_request(self, bot, method, timeout=None):
        """Return successful callback acknowledgments through the fake transport."""
        if isinstance(method, AnswerCallbackQuery | EditMessageText):
            self.methods.append(method)
            return True
        return await super().make_request(bot, method, timeout)


def update(actor, text, identifier=1, chat_type="private"):
    """Build a synthetic message with explicit sender and event identity."""
    return Update(
        update_id=identifier,
        message=Message(
            message_id=identifier,
            date=datetime.now(UTC),
            chat=Chat(id=actor, type=chat_type),
            from_user=User(id=actor, is_bot=False, first_name="Synthetic"),
            text=text,
        ),
    )


def callback(actor, data, identifier=100):
    """Build a callback attached to a private administrative message."""
    return Update(
        update_id=identifier,
        callback_query=CallbackQuery(
            id=str(identifier),
            from_user=User(id=actor, is_bot=False, first_name="Synthetic"),
            chat_instance="synthetic",
            data=data,
            message=Message(
                message_id=50, date=datetime.now(UTC), chat=Chat(id=actor, type="private")
            ),
        ),
    )


def test_private_menu_profile_and_manual_stock(recognition):
    """Use real handlers to register, store a purchase and read private inventory."""

    async def run():
        async with database() as (service, _):
            session = Session(b"")
            bot = Bot("123456:TEST", session=session)
            dispatcher = create_dispatcher(PhotoTrial(FakeRecognizer(recognition), None), service)
            await dispatcher.feed_update(bot, update(1, "/start"))
            assert any(
                isinstance(method, SendMessage) and method.reply_markup
                for method in session.methods
            )
            await dispatcher.feed_update(bot, update(1, "/add Молоко | 2 | l | 2026-11-05", 2))
            await dispatcher.feed_update(bot, update(1, "/add Молоко | 2 | l | 2026-11-05", 2))
            assert len(await service.inventory(1)) == 1
            await dispatcher.feed_update(bot, update(1, "Личный кабинет", 3))
            assert "Личный кабинет" in session.methods[-1].text
            await dispatcher.feed_update(bot, update(2, "/start", 4))
            assert await service.inventory(2) == []
            await bot.session.close()

    asyncio.run(run())


def test_admin_confirmation_is_actor_bound_and_cannot_replay():
    """Forged and repeated confirmations cannot change another actor's intent."""

    async def run():
        async with database() as (service, _):
            target = await service.register(1, "Target")
            session = Session(b"")
            bot = Bot("654321:TEST", session=session)
            dispatcher = create_admin_dispatcher(service, frozenset({99}))
            await dispatcher.feed_update(bot, update(2, "/start"))
            assert session.methods[-1].text == "Доступ запрещён."
            await dispatcher.feed_update(bot, update(99, "/start", 2))
            await dispatcher.feed_update(bot, update(99, f"/block {target.id} Test reason", 3))
            markup = session.methods[-1].reply_markup
            data = markup.inline_keyboard[0][0].callback_data
            await dispatcher.feed_update(bot, callback(2, data))
            assert not (await service.profile(1)).blocked
            await dispatcher.feed_update(bot, callback(99, data, 101))
            assert (await service.admin_target(99, target.id)).blocked
            version = (await service.admin_target(99, target.id)).version
            await dispatcher.feed_update(bot, callback(99, data, 102))
            assert (await service.admin_target(99, target.id)).version == version
            await bot.session.close()

    asyncio.run(run())


def test_cancel_admin_confirmation_and_group_denial():
    """Cancellation preserves status; group messages never disclose user metadata."""

    async def run():
        async with database() as (service, _):
            target = await service.register(1, "Target")
            session = Session(b"")
            bot = Bot("654321:TEST", session=session)
            dispatcher = create_admin_dispatcher(service, frozenset({99}))
            await dispatcher.feed_update(bot, update(99, "/start"))
            await dispatcher.feed_update(bot, update(99, f"/block {target.id} Reason", 2))
            data = session.methods[-1].reply_markup.inline_keyboard[0][1].callback_data
            await dispatcher.feed_update(bot, callback(99, data))
            assert not (await service.profile(1)).blocked
            count = len(session.methods)
            await dispatcher.feed_update(bot, update(99, "/users", 3, "group"))
            assert len(session.methods) == count
            await bot.session.close()

    asyncio.run(run())
