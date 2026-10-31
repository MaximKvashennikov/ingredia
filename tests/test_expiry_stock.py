"""Purchase estimates and compact inventory behavior without live AI or Telegram."""

import asyncio
import os
from datetime import date, timedelta

import pytest
from aiogram import Bot
from aiogram.methods import EditMessageText, SendMessage
from test_accounts import database
from test_navigation import Session, callback, update
from test_telegram import FakeRecognizer, photo_update

from ingredia.accounts.expiry import estimate_expiry
from ingredia.accounts.models import AccessDenied, BatchInput
from ingredia.adapters.telegram import create_dispatcher
from ingredia.adapters.telegram.models import PhotoJob
from ingredia.adapters.telegram.views import stock_card
from ingredia.clock import current_date
from ingredia.recognition.errors import FailureCode, RecognitionFailure
from ingredia.recognition.service import PhotoTrial


@pytest.mark.parametrize("postgres", [False, True])
def test_purchase_estimates_explicit_dates_and_opt_out(recognition, postgres):
    """Preview dates persist separately, never override labels and can be declined."""
    if postgres and not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("PostgreSQL not configured")
    url = os.environ["TEST_DATABASE_URL"] if postgres else "sqlite+aiosqlite:///:memory:"

    async def run():
        async with database(url) as (service, _):
            await service.register(1, "Owner")
            draft = await service.preview_purchase(1, "estimate", recognition)
            assert (await service.inventory(1)) == []
            estimate = draft.estimates[0]
            assert estimate.expiry == current_date() + timedelta(days=7)
            repeated = await service.preview_purchase(1, "estimate", recognition)
            assert repeated == draft
            await service.decide_purchase(1, str(draft.id), True)
            item = (await service.inventory(1))[0]
            assert item.expiry == estimate.expiry and item.expiry_source == "estimated"
            assert item.expiry_estimate.source.startswith("https://food.unl.edu/")
            assert "по оценке" in stock_card(item) and "4 °C" in stock_card(item)
            explicit = recognition.model_copy(deep=True)
            explicit.products[0].expiry_date = current_date() + timedelta(days=2)
            explicit.products[0].expiry_evidence = "Синтетическая маркировка"
            labeled = await service.preview_purchase(1, "labeled", explicit)
            assert labeled.estimates == [None]
            await service.decide_purchase(1, str(labeled.id), True)
            labeled_stock = await service.stock_item(
                1,
                next(
                    row.id for row in await service.inventory(1) if row.expiry_source == "confirmed"
                ),
            )
            assert labeled_stock.expiry == explicit.products[0].expiry_date
            assert labeled_stock.expiry_estimate is None
            plain = await service.preview_purchase(1, "plain", recognition)
            await service.decide_purchase(1, str(plain.id), True, use_estimates=False)
            unknown = [row for row in await service.inventory(1) if row.expiry_source == "unknown"]
            assert len(unknown) == 1 and unknown[0].expiry is None

    asyncio.run(run())


@pytest.mark.parametrize(
    "name", ["Молоко сгущённое", "Салат с яйцом", "Курица копчёная", "Неизвестный соус"]
)
def test_ambiguous_product_forms_get_no_fabricated_estimate(recognition, name):
    """Conservative matching cannot apply a raw or plain rule to a processed food."""
    item = recognition.products[0].model_copy(update={"name": name})
    assert estimate_expiry(item, date(2026, 10, 30)) is None


def test_compact_fridge_edit_navigation_and_owner_cards(recognition):
    """Six product selectors replace long lists, refresh edits and foreign cards stay hidden."""

    async def run():
        async with database() as (service, _):
            await service.register(1, "Owner")
            await service.register(2, "Other")
            for i in range(7):
                await service.add(
                    1, str(i), BatchInput(name=f"Продукт {i}", quantity=2, unit="pcs")
                )
            page = await service.stock_page(1)
            assert page.total == 7 and len(page.items) == 6 and page.has_next
            assert len((await service.stock_page(1, 1)).items) == 1
            session = Session(b"")
            bot = Bot("123456:TEST", session=session)
            dispatcher = create_dispatcher(PhotoTrial(FakeRecognizer(recognition), None), service)
            await dispatcher.feed_update(bot, update(1, "Мой холодильник"))
            screen = session.methods[-1]
            assert isinstance(screen, SendMessage)
            assert len(screen.text) < 250 and "Продукт 0" not in screen.text
            assert "\n" in screen.text and r"\n" not in screen.text
            products = [
                button
                for row in screen.reply_markup.inline_keyboard
                for button in row
                if button.callback_data.startswith("stock:")
            ]
            assert len(products) == 6
            await dispatcher.feed_update(bot, callback(2, products[0].callback_data))
            assert not isinstance(session.methods[-1], EditMessageText)
            assert "недоступен" in session.methods[-1].text
            await dispatcher.feed_update(bot, callback(1, products[0].callback_data, 101))
            assert isinstance(session.methods[-1], EditMessageText)
            assert "Продукт 0" in session.methods[-1].text
            await dispatcher.feed_update(bot, callback(1, "fridge:1", 102))
            assert "Страница 2 из 2" in session.methods[-1].text
            assert isinstance(session.methods[-1], EditMessageText)
            with pytest.raises(AccessDenied):
                await service.stock_item(2, page.items[0].id)

    asyncio.run(run())


def test_photo_failure_logs_category_without_private_content(jpeg, caplog):
    """The observed logging gap is covered for the actual purchase handler path."""

    class FailingRecognizer:
        """Fail safely after receiving the prepared synthetic photograph."""

        async def recognize(self, photo):
            """Simulate an unavailable provider without making a request."""
            raise RecognitionFailure(FailureCode.INVALID_RESPONSE)

    async def run():
        async with database() as (service, _):
            bot = Bot("123456:TEST", session=Session(jpeg))
            dispatcher = create_dispatcher(PhotoTrial(FailingRecognizer(), None, 0), service)
            await dispatcher.feed_update(bot, photo_update())
            assert (
                "Purchase recognition failed: input=photo category=invalid_response" in caplog.text
            )

    asyncio.run(run())


def test_photo_sent_as_image_document_uses_the_same_purchase_flow(jpeg, recognition):
    """Sending a JPEG as a file is recognized instead of falling through to unsupported."""
    from aiogram.types import Document

    async def run():
        async with database() as (service, _):
            session = Session(jpeg)
            bot = Bot("123456:TEST", session=session)
            recognizer = FakeRecognizer(recognition)
            dispatcher = create_dispatcher(PhotoTrial(recognizer, None, 0), service)
            event = photo_update()
            document = Document(
                file_id="image-file",
                file_unique_id="document-unique",
                file_name="photo.jpg",
                mime_type="image/jpeg",
                file_size=len(jpeg),
            )
            event = event.model_copy(
                update={
                    "message": event.message.model_copy(
                        update={"photo": None, "document": document}
                    )
                }
            )
            assert PhotoJob.from_message(event.message).file_id == "image-file"
            await dispatcher.feed_update(bot, event)
            assert recognizer.calls == 1
            assert any(
                "Проверьте покупки" in getattr(method, "text", "") for method in session.methods
            )
            assert await service.inventory(1) == []

    asyncio.run(run())
