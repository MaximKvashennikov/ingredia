"""Receipt photo contracts and expiry pagination without real AI or Telegram requests."""

import asyncio
import json
import os
from datetime import date, timedelta

import httpx
import pytest
from aiogram import Bot
from aiogram.methods import EditMessageText, GetFile, SendMessage, SendRichMessage
from aiogram.types import Audio, Voice
from pydantic import SecretStr
from test_accounts import database
from test_navigation import Session, callback, rich_buttons, update
from test_provider_selection import settings
from test_telegram import FakeRecognizer, photo_update

from ingredia.accounts.models import BatchInput
from ingredia.accounts.service import AccountService
from ingredia.adapters.telegram import create_dispatcher
from ingredia.adapters.telegram.purchases import PurchaseHandlers
from ingredia.providers import create_recognizers
from ingredia.recognition.models import PhotoRecognition
from ingredia.recognition.service import PhotoTrial
from ingredia.storage.models import Batch


def receipt_observations():
    """Represent synthetic food lines from an unlabelled receipt with no expiry evidence."""
    common = {
        "brand": None,
        "expiry_date": None,
        "expiry_evidence": None,
        "needs_clarification": False,
        "clarification_question": None,
    }
    return PhotoRecognition.model_validate(
        {
            "products": [
                dict(
                    common,
                    name="Молоко",
                    visual_description="Строка чека: молоко 2 × 1 л",
                    package_count=2,
                    quantity_per_package={
                        "value": 1,
                        "unit": "l",
                        "evidence": "2 шт, фасовка 1 л",
                    },
                ),
                dict(
                    common,
                    name="Яблоки",
                    visual_description="Строка чека: яблоки весовые",
                    package_count=None,
                    quantity_per_package={
                        "value": 0.743,
                        "unit": "kg",
                        "evidence": "Вес 0,743 кг",
                    },
                ),
            ],
            "warnings": ["Дата чека относится к покупке, срок годности не указан"],
        }
    )


@pytest.mark.parametrize("provider", ["groq", "zai"])
def test_receipt_photo_preview_save_and_no_duplicate_requests(provider, jpeg):
    """Both providers use receipt instructions; validated counts reach stock only after confirmation."""

    async def run():
        calls = []

        def respond(request):
            calls.append(request)
            body = json.loads(request.content)
            prompt = body["messages"][0]["content"]
            assert "Магазинный чек" in prompt and "Фото продуктов" in prompt
            assert "Цена в рублях" in prompt and "НЕ срок годности" in prompt
            assert "недоверенные данные" in prompt
            assert body["messages"][1]["content"][1]["image_url"]["url"].startswith(
                "data:image/jpeg"
            )
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": receipt_observations().model_dump_json()},
                            "finish_reason": "stop",
                        }
                    ]
                },
            )

        async with database() as (accounts, _):
            session = Session(jpeg)
            bot = Bot("123456:TEST", session=session)
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                ports = create_recognizers(
                    settings(provider, **{provider: SecretStr("fake-key")}), client
                )
                dispatcher = create_dispatcher(PhotoTrial(ports.photo, None, 0), accounts)
                await dispatcher.feed_update(bot, photo_update())
                assert await accounts.inventory(1) == []
                messages = [method for method in session.methods if isinstance(method, SendMessage)]
                assert any("0.743 кг" in method.text for method in messages)
                assert any("по оценке" in method.text for method in messages)
                token = messages[-1].reply_markup.inline_keyboard[0][0].callback_data
                await dispatcher.feed_update(bot, callback(1, token))
                rows = {row.name: row for row in await accounts.inventory(1)}
                assert rows["Молоко"].quantity == 2 and rows["Молоко"].unit == "l"
                assert str(rows["Яблоки"].quantity) == "0.743"
                assert rows["Яблоки"].unit == "kg"
                assert all(row.expiry_source == "estimated" for row in rows.values())
                await dispatcher.feed_update(bot, callback(1, token, 101))
                assert len(await accounts.inventory(1)) == 2
                assert len(calls) == 1

    asyncio.run(run())


def test_empty_receipt_shows_readability_warning_and_never_saves():
    """A too-long or unreadable receipt gives actionable guidance instead of losing its warning."""

    async def run():
        async with database() as (accounts, _):
            await accounts.register(1, "Owner")
            session = Session(b"")
            bot = Bot("123456:TEST", session=session)
            result = PhotoRecognition(
                products=[], warnings=["Пришлите чек частями, до 20 продуктов"]
            )
            handlers = PurchaseHandlers(PhotoTrial(FakeRecognizer(result), None), accounts)
            message = update(1, "synthetic").message.as_(bot)
            await handlers.present(message, result)
            assert "Пришлите чек частями" in session.methods[-1].text
            assert session.methods[-1].reply_markup is None
            assert await accounts.inventory(1) == []

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["voice", "audio"])
def test_audio_is_rejected_before_download_or_cloud_call(kind, jpeg):
    """Unsupported audio explains the replacement inputs without consuming recognition quota."""

    async def run():
        async with database() as (accounts, _):
            session = Session(jpeg)
            bot = Bot("123456:TEST", session=session)
            recognizer = FakeRecognizer(receipt_observations())
            dispatcher = create_dispatcher(PhotoTrial(recognizer, None), accounts)
            media_type = Voice if kind == "voice" else Audio
            media = media_type(file_id="synthetic", file_unique_id="synthetic", duration=2)
            event = photo_update()
            event = event.model_copy(
                update={"message": event.message.model_copy(update={"photo": None, kind: media})}
            )
            await dispatcher.feed_update(bot, event)
            assert "не распознаются" in session.methods[-1].text
            assert "чека" in session.methods[-1].text and "продуктов" in session.methods[-1].text
            assert not any(isinstance(method, GetFile) for method in session.methods)
            assert recognizer.calls == 0
            assert await accounts.inventory(1) == []

    asyncio.run(run())


@pytest.mark.parametrize("postgres", [False, True])
def test_expiry_order_across_pages_unknown_last_and_stable_refresh(postgres):
    """Sorting applies before pagination and equal dates remain stable across repeated screens."""
    if postgres and not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("PostgreSQL not configured")
    url = os.environ["TEST_DATABASE_URL"] if postgres else "sqlite+aiosqlite:///:memory:"
    today = date(2026, 11, 18)

    async def run():
        async with database(url) as (_, sessions):
            accounts = AccountService(sessions, frozenset(), today=lambda: today)
            await accounts.register(1, "Owner")
            await accounts.register(2, "Other")
            items = [
                ("А неизвестный", None),
                ("Я дальний", 9),
                ("Я ближайший", 1),
                ("А сегодня", 0),
                ("Просроченный", -1),
                ("Равный", 2),
                ("Равный", 2),
                ("Середина", 4),
                ("Я неизвестный", None),
            ]
            for i, (name, days) in enumerate(items):
                await accounts.add(
                    1,
                    str(i),
                    BatchInput(
                        name=name,
                        expiry=today + timedelta(days=days) if days is not None else None,
                    ),
                )
            async with sessions.begin() as session:
                from sqlalchemy import select

                unknowns = await session.scalars(
                    select(Batch).where(Batch.name.in_(["А неизвестный", "Я неизвестный"]))
                )
                for row in unknowns:
                    row.expiry, row.expiry_source, row.expiry_estimate = None, "declined", None
            await accounts.add(
                2, "foreign", BatchInput(name="Чужой", expiry=today - timedelta(days=2))
            )
            first = await accounts.stock_page(1)
            second = await accounts.stock_page(1, 1)
            assert first.total == 9 and first.has_next and not second.has_next
            rows = first.items + second.items
            assert [row.name for row in rows] == [
                "Просроченный",
                "А сегодня",
                "Я ближайший",
                "Равный",
                "Равный",
                "Середина",
                "Я дальний",
                "А неизвестный",
                "Я неизвестный",
            ]
            assert rows[3].id < rows[4].id
            assert [row.id for row in (await accounts.stock_page(1)).items] == [
                row.id for row in first.items
            ]
            session = Session(b"")
            bot = Bot("123456:TEST", session=session)
            dispatcher = create_dispatcher(
                PhotoTrial(FakeRecognizer(receipt_observations()), None),
                accounts,
            )
            await dispatcher.feed_update(bot, update(1, "Мой холодильник"))
            await dispatcher.feed_update(bot, callback(1, "fridge:1"))
            assert isinstance(session.methods[-1], EditMessageText)
            labels = [
                button.text
                for button in rich_buttons(session.methods[-1])
                if button.callback_data.startswith("stock:")
            ]
            assert len(labels) == 3 and "Я дальний" in labels[0]
            await dispatcher.feed_update(bot, callback(1, "fridge:0", 101))
            await dispatcher.feed_update(bot, callback(1, "fridge:0", 102))
            assert (
                len(
                    [
                        method
                        for method in session.methods
                        if isinstance(method, SendMessage | SendRichMessage)
                    ]
                )
                == 1
            )

    asyncio.run(run())
