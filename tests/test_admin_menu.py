"""Administrative button flows through real handlers and isolated persistence."""

import asyncio
import os

import pytest
from aiogram import Bot
from aiogram.methods import AnswerCallbackQuery, SendMessage
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import update as sql_update
from test_accounts import database
from test_navigation import Session, callback, update

from ingredia.accounts.models import AccessDenied, AccountFilter
from ingredia.adapters.telegram_admin.menu import AdminMenu
from ingredia.adapters.telegram_admin.router import create_admin_dispatcher
from ingredia.storage.models import Account


def last_message(session):
    """Read the last actual message, ignoring callback acknowledgments."""
    return next(method for method in reversed(session.methods) if isinstance(method, SendMessage))


def button(message, text):
    """Find an action by its visible label rather than internal handler state."""
    return next(
        item.callback_data
        for row in message.reply_markup.inline_keyboard
        for item in row
        if text in item.text
    )


async def send(dispatcher, bot, text, identifier=1, actor=99):
    """Deliver a synthetic private message without live Telegram requests."""
    await dispatcher.feed_update(bot, update(actor, text, identifier))


async def press(dispatcher, bot, data, identifier=100, actor=99):
    """Deliver a synthetic private button press."""
    await dispatcher.feed_update(bot, callback(actor, data, identifier))


def test_admin_menu_and_button_block_unblock():
    """An administrator can manage access without copying an ID or typing a command."""

    async def run():
        async with database() as (service, _):
            target = await service.register(1, "Target <tag>")
            session = Session(b"")
            bot = Bot("654321:TEST", session=session)
            dispatcher = create_admin_dispatcher(service, frozenset({99}))
            await send(dispatcher, bot, "/start")
            labels = [
                item.text for row in last_message(session).reply_markup.keyboard for item in row
            ]
            assert AdminMenu.USERS in labels and AdminMenu.SEARCH in labels
            for blocked in (True, False):
                await send(dispatcher, bot, AdminMenu.USERS)
                listing = last_message(session)
                await press(dispatcher, bot, button(listing, "Target"))
                card = last_message(session)
                assert "Target &lt;tag&gt;" in card.text
                assert card.parse_mode == "HTML"
                action = "Заблокировать" if blocked else "Разблокировать"
                await press(dispatcher, bot, button(card, action))
                assert "причину" in last_message(session).text
                await send(dispatcher, bot, "Synthetic reason", 20)
                assert (await service.admin_target(99, target.id)).blocked is not blocked
                confirm = last_message(session)
                await press(dispatcher, bot, button(confirm, action), 201)
                assert (await service.admin_target(99, target.id)).blocked is blocked
                assert "✅" in last_message(session).text
            await send(dispatcher, bot, AdminMenu.BLOCKED)
            assert "Никого не найдено" in last_message(session).text

    asyncio.run(run())


def test_search_pagination_and_return_preserve_filter():
    """Opening a card and going back retains a filtered query and its second page."""

    async def run():
        async with database() as (service, _):
            for identifier in range(1, 13):
                await service.register(identifier, "Searchable name")
            await service.register(20, "Other")
            session = Session(b"")
            bot = Bot("654321:TEST", session=session)
            dispatcher = create_admin_dispatcher(service, frozenset({99}))
            await send(dispatcher, bot, "/start")
            await send(dispatcher, bot, AdminMenu.USERS)
            await press(dispatcher, bot, button(last_message(session), "Активные"))
            await send(dispatcher, bot, AdminMenu.SEARCH)
            await send(dispatcher, bot, "Searchable", 5)
            assert "Найдено: 12" in last_message(session).text
            await press(dispatcher, bot, button(last_message(session), "Далее"))
            second = last_message(session)
            assert "Страница 2" in second.text
            await press(dispatcher, bot, button(second, "Searchable"))
            await press(dispatcher, bot, button(last_message(session), "К списку"))
            returned = last_message(session)
            assert "Страница 2" in returned.text
            assert "Searchable" in returned.text and "Активные" in returned.text
            assert not any(
                "Далее" in item.text
                for row in returned.reply_markup.inline_keyboard
                for item in row
            )

    asyncio.run(run())


def test_search_numeric_id_and_literal_wildcards():
    """Search treats wildcard characters literally and accepts either stable ID."""

    async def run():
        async with database() as (service, _):
            target = await service.register(1, "100%_match")
            await service.register(2, "100XXmatch")
            await service.register(99, "Admin")
            for query in ("1", target.id, "%_"):
                result = await service.user_directory(99, query=query)
                assert [row.id for row in result.items] == [target.id]
            assert (await service.user_directory(99, query="missing")).total == 0
            assert (await service.user_directory(99, query="9" * 128)).total == 0
            with pytest.raises(AccessDenied):
                await service.user_directory(2, query=target.id)

    asyncio.run(run())


def test_back_and_home_cancel_unfinished_changes():
    """Leaving a reason or confirmation screen cannot leave a usable old status intent."""

    async def run():
        async with database() as (service, _):
            await service.register(1, "Target")
            session = Session(b"")
            bot = Bot("654321:TEST", session=session)
            dispatcher = create_admin_dispatcher(service, frozenset({99}))
            await send(dispatcher, bot, "/start")
            await send(dispatcher, bot, AdminMenu.USERS)
            await press(dispatcher, bot, button(last_message(session), "Target"))
            stale = button(last_message(session), "Заблокировать")
            await press(dispatcher, bot, stale)
            await send(dispatcher, bot, AdminMenu.BACK)
            await press(dispatcher, bot, stale)
            assert "устарела" in session.methods[-1].text
            assert not (await service.profile(1)).blocked
            await press(dispatcher, bot, button(last_message(session), "Заблокировать"))
            await send(dispatcher, bot, "Reason")
            confirmation = button(last_message(session), "Заблокировать")
            await send(dispatcher, bot, AdminMenu.HOME)
            await press(dispatcher, bot, confirmation)
            assert not (await service.profile(1)).blocked

    asyncio.run(run())


def test_admin_card_has_no_self_block_action():
    """Trusted administrative accounts are viewable but have no status mutation button."""

    async def run():
        async with database() as (service, _):
            session = Session(b"")
            bot = Bot("654321:TEST", session=session)
            dispatcher = create_admin_dispatcher(service, frozenset({99}))
            await send(dispatcher, bot, "/start")
            await send(dispatcher, bot, AdminMenu.USERS)
            await press(dispatcher, bot, button(last_message(session), "99"))
            card = last_message(session)
            assert "Администратор" in card.text
            assert not any(
                item.callback_data.startswith("act:")
                for row in card.reply_markup.inline_keyboard
                for item in row
            )

    asyncio.run(run())


def test_revoked_access_rejects_menu_search_and_callbacks():
    """Every text step and callback checks current account state."""

    async def run():
        async with database() as (service, sessions):
            await service.register(1, "Target")
            session = Session(b"")
            bot = Bot("654321:TEST", session=session)
            dispatcher = create_admin_dispatcher(service, frozenset({99}))
            await send(dispatcher, bot, "/start")
            await send(dispatcher, bot, AdminMenu.USERS)
            action = button(last_message(session), "Target")
            await send(dispatcher, bot, AdminMenu.SEARCH)
            async with sessions.begin() as db:
                await db.execute(
                    sql_update(Account).where(Account.telegram_id == 99).values(blocked=True)
                )
            await send(dispatcher, bot, "Target")
            assert last_message(session).text == "Доступ запрещён."
            await press(dispatcher, bot, action)
            assert isinstance(session.methods[-1], AnswerCallbackQuery)
            assert session.methods[-1].text == "Доступ запрещён."

    asyncio.run(run())


def test_new_search_and_other_admin_cannot_reuse_directory_buttons():
    """Opaque list controls are bound to the latest query and the originating administrator."""

    async def run():
        admins = frozenset({99, 100})
        async with database(admins=admins) as (service, _):
            await service.register(1, "Target")
            session = Session(b"")
            bot = Bot("654321:TEST", session=session)
            dispatcher = create_admin_dispatcher(service, admins)
            await send(dispatcher, bot, "/start")
            await send(dispatcher, bot, AdminMenu.USERS)
            old = button(last_message(session), "Target")
            await send(dispatcher, bot, "/start", actor=100)
            await press(dispatcher, bot, old, actor=100)
            assert "устарел" in session.methods[-1].text
            await send(dispatcher, bot, AdminMenu.SEARCH)
            await send(dispatcher, bot, "Missing")
            await press(dispatcher, bot, old)
            assert "устарел" in session.methods[-1].text

    asyncio.run(run())


def test_reason_validation_and_callback_size():
    """Oversized reasons preserve the input step; all generated controls fit Telegram limits."""

    async def run():
        async with database() as (service, _):
            await service.register(1, "Target")
            session = Session(b"")
            bot = Bot("654321:TEST", session=session)
            dispatcher = create_admin_dispatcher(service, frozenset({99}))
            await send(dispatcher, bot, "/start")
            await send(dispatcher, bot, AdminMenu.USERS)
            await press(dispatcher, bot, button(last_message(session), "Target"))
            await press(dispatcher, bot, button(last_message(session), "Заблокировать"))
            await send(dispatcher, bot, "x" * 201)
            assert "200" in last_message(session).text
            await send(dispatcher, bot, "<reason>")
            assert "&lt;reason&gt;" in last_message(session).text
            for method in session.methods:
                if isinstance(method, SendMessage) and isinstance(
                    method.reply_markup, InlineKeyboardMarkup
                ):
                    for row in method.reply_markup.inline_keyboard:
                        assert all(len(item.callback_data.encode("utf-8")) <= 64 for item in row)

    asyncio.run(run())


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="PostgreSQL server not configured")
def test_postgresql_directory_search_and_filter():
    """PostgreSQL applies case-insensitive Cyrillic search, IDs and status filters."""

    async def run():
        async with database(os.environ["TEST_DATABASE_URL"]) as (service, _):
            target = await service.register(1, "Борис")
            await service.register(99, "Admin")
            await service.change_status(99, target.id, 1, True, "Reason")
            result = await service.user_directory(99, query="борис", status=AccountFilter.BLOCKED)
            assert [row.id for row in result.items] == [target.id]
            assert (
                await service.user_directory(99, query="борис", status=AccountFilter.ACTIVE)
            ).total == 0

    asyncio.run(run())
