"""Photo-first and free-text purchases tested without live providers."""

import asyncio
import os

import httpx
import pytest
from aiogram import Bot
from aiogram.methods import SendDocument, SendMessage
from pydantic import SecretStr
from test_accounts import database
from test_navigation import Session, callback, update
from test_telegram import FakeRecognizer, photo_update

from ingredia.accounts.models import AccessDenied, Conflict
from ingredia.adapters.telegram import create_dispatcher
from ingredia.adapters.telegram.menu import keyboard
from ingredia.adapters.zai.text_recognizer import ZaiTextRecognizer
from ingredia.recognition.service import PhotoTrial


class TextRecognizer:
    """Return a known candidate list and count provider calls."""

    def __init__(self, result):
        """Inject a deterministic synthetic result."""
        self.result = result
        self.calls = 0

    async def recognize_text(self, text):
        """Extract synthetic products without a network request."""
        self.calls += 1
        return self.result


def test_photo_purchase_preview_confirm_and_replay(jpeg, recognition):
    """A photo shows human cards and saves only after an owner confirmation."""

    async def run():
        async with database() as (service, _):
            session = Session(jpeg)
            bot = Bot("123456:TEST", session=session)
            dispatcher = create_dispatcher(
                PhotoTrial(FakeRecognizer(recognition), None, 0), service
            )
            await dispatcher.feed_update(bot, photo_update())
            assert not any(isinstance(method, SendDocument) for method in session.methods)
            assert await service.inventory(1) == []
            messages = [method for method in session.methods if isinstance(method, SendMessage)]
            assert any("Проверьте покупки" in method.text for method in messages)
            assert any("Молоко" in method.text and "2 × 1 л" in method.text for method in messages)
            token = messages[-1].reply_markup.inline_keyboard[0][0].callback_data
            await dispatcher.feed_update(bot, callback(2, token))
            assert await service.inventory(1) == []
            await dispatcher.feed_update(bot, callback(1, token, 101))
            stock = await service.inventory(1)
            assert len(stock) == 1 and stock[0].quantity == 2 and stock[0].unit == "l"
            await dispatcher.feed_update(bot, callback(1, token, 102))
            assert len(await service.inventory(1)) == 1

    asyncio.run(run())


def test_free_text_cancel_and_replacement(recognition):
    """Natural text creates a preview; cancellation and replacement prevent stale writes."""

    async def run():
        async with database() as (service, _):
            session = Session(b"")
            bot = Bot("123456:TEST", session=session)
            text = TextRecognizer(recognition)
            dispatcher = create_dispatcher(
                PhotoTrial(FakeRecognizer(recognition), None, 0, text_recognizer=text),
                service,
            )
            await dispatcher.feed_update(bot, update(1, "Купил два литра молока"))
            old = session.methods[-1].reply_markup.inline_keyboard[0][0].callback_data
            await dispatcher.feed_update(bot, update(1, "Купил две пачки молока по литру", 2))
            cancel = session.methods[-1].reply_markup.inline_keyboard[1][0].callback_data
            await dispatcher.feed_update(bot, callback(1, old))
            assert await service.inventory(1) == []
            await dispatcher.feed_update(bot, callback(1, cancel, 101))
            assert await service.inventory(1) == []
            assert text.calls == 2

    asyncio.run(run())


@pytest.mark.parametrize("postgres", [False, True])
def test_purchase_atomic_access_and_restart(recognition, postgres):
    """Persistent previews survive service recreation and enforce access and transaction limits."""
    if postgres and not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("PostgreSQL not configured")
    url = os.environ["TEST_DATABASE_URL"] if postgres else "sqlite+aiosqlite:///:memory:"

    async def run():
        async with database(url) as (service, sessions):
            await service.register(1, "Owner")
            await service.register(2, "Other")
            preview = await service.preview_purchase(1, "one", recognition)
            from ingredia.accounts.service import AccountService

            fresh = AccountService(sessions, frozenset({99}))
            with pytest.raises(AccessDenied):
                await fresh.decide_purchase(2, str(preview.id), True)
            assert await fresh.decide_purchase(1, str(preview.id), True) == 1
            with pytest.raises(Conflict):
                await fresh.decide_purchase(1, str(preview.id), True)
            assert len(await fresh.inventory(1)) == 1

    asyncio.run(run())


def test_unclear_purchase_cannot_be_saved(recognition):
    """A missing name and clarification question never become a guessed stock row."""
    unclear = recognition.model_copy(deep=True)
    unclear.products[0].name = None
    unclear.products[0].needs_clarification = True
    unclear.products[0].clarification_question = "Что в белой упаковке?"

    async def run():
        async with database() as (service, _):
            await service.register(1, "Owner")
            draft = await service.preview_purchase(1, "unclear", unclear)
            with pytest.raises(Conflict):
                await service.decide_purchase(1, str(draft.id), True)
            assert await service.inventory(1) == []

    asyncio.run(run())


def test_free_text_uses_selected_free_model(recognition):
    """Validate the free text model payload and structured output contract."""

    async def run():
        async def respond(request):
            import json

            payload = json.loads(request.content)
            assert payload["model"] == "glm-4.7-flash"
            assert payload["messages"][1]["content"] == "Купил два литра молока"
            assert "tools" not in payload
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": recognition.model_dump_json()},
                            "finish_reason": "stop",
                        }
                    ]
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            recognizer = ZaiTextRecognizer(client, SecretStr("fake-key"))
            assert await recognizer.recognize_text("Купил два литра молока") == recognition

    asyncio.run(run())


def test_menu_has_icons_with_text_labels():
    """Icons accompany descriptive button labels instead of replacing them."""
    labels = [button.text for row in keyboard().keyboard for button in row]
    assert "🛒 Добавить покупки" in labels
    assert "🧊 Мой холодильник" in labels
    assert all(len(label.split()) >= 2 for label in labels)
