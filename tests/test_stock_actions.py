"""Confirmed destructive actions and automatic expiry behavior with fake Telegram transports."""

import asyncio
import os
from datetime import UTC, date, datetime, timedelta

import pytest
from aiogram import Bot
from aiogram.methods import EditMessageText, SendMessage, SendRichMessage
from sqlalchemy import event, func, select
from sqlalchemy.exc import SQLAlchemyError
from test_accounts import database
from test_navigation import Session, callback, rich_buttons, update, visible_text
from test_telegram import FakeRecognizer

from ingredia.accounts.expiry import estimate_name
from ingredia.accounts.models import AccessDenied, BatchInput, Conflict
from ingredia.adapters.telegram import create_dispatcher
from ingredia.adapters.telegram.views import stock_card
from ingredia.clock import current_date
from ingredia.recognition.service import PhotoTrial
from ingredia.storage.models import Batch, Recipe, RemovedStockEvent, StockRemovalDraft


@pytest.mark.parametrize("postgres", [False, True])
def test_removal_owner_cancel_clear_snapshot_replay_and_favorites(postgres):
    """Deletion is owner-bound, explicit, idempotent and cannot delete new undisplayed purchases."""
    if postgres and not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("PostgreSQL not configured")
    url = os.environ["TEST_DATABASE_URL"] if postgres else "sqlite+aiosqlite:///:memory:"

    async def run():
        async with database(url) as (accounts, sessions):
            owner = await accounts.register(1, "Owner")
            await accounts.register(2, "Other")
            first = await accounts.add(1, "first", BatchInput(name="Молоко"))
            second = await accounts.add(1, "second", BatchInput(name="Яблоки"))
            foreign = await accounts.add(2, "foreign", BatchInput(name="Чужой"))
            async with sessions.begin() as session:
                recipe = Recipe(owner_id=owner.id, payload={"synthetic": True}, favorite=True)
                session.add(recipe)
                await session.flush()
                favorite_id = recipe.id
            with pytest.raises(AccessDenied):
                await accounts.removals.plan(1, foreign.id)
            plan = await accounts.removals.plan(1, first.id)
            assert plan.count == 1 and plan.name == "Молоко"
            assert len(await accounts.inventory(1)) == 2
            with pytest.raises(AccessDenied):
                await accounts.removals.decide(2, str(plan.id), True)
            assert await accounts.removals.decide(1, str(plan.id), False) == 0
            assert len(await accounts.inventory(1)) == 2
            with pytest.raises(Conflict):
                await accounts.removals.decide(1, str(plan.id), True)
            remove_one = await accounts.removals.plan(1, first.id)
            assert await accounts.removals.decide(1, str(remove_one.id), True) == 1
            with pytest.raises(Conflict):
                await accounts.add(1, "first", BatchInput(name="Replay"))
            with pytest.raises(Conflict):
                await accounts.removals.decide(1, str(remove_one.id), True)
            all_old = await accounts.removals.plan(1)
            third = await accounts.add(1, "third", BatchInput(name="Огурцы"))
            with pytest.raises(Conflict):
                await accounts.removals.decide(1, str(all_old.id), True)
            assert {row.id for row in await accounts.inventory(1)} == {second.id, third.id}
            clear = await accounts.removals.plan(1)
            assert clear.count == 2 and clear.name is None
            assert await accounts.removals.decide(1, str(clear.id), True) == 2
            assert await accounts.inventory(1) == []
            assert len(await accounts.inventory(2)) == 1
            async with sessions() as session:
                assert (await session.get(Recipe, favorite_id)).favorite
                assert (
                    await session.scalar(select(func.count()).select_from(RemovedStockEvent)) == 3
                )

    asyncio.run(run())


def test_stale_versions_expired_confirmations_and_blocked_actors():
    """A changed row, expired token, replaced draft or newly blocked actor cannot be deleted."""

    async def run():
        async with database() as (accounts, sessions):
            owner = await accounts.register(1, "Owner")
            await accounts.register(99, "Admin")
            first = await accounts.add(1, "first", BatchInput(name="Молоко"))
            old = await accounts.removals.plan(1, first.id)
            async with sessions.begin() as session:
                row = await session.get(Batch, first.id)
                row.version += 1
            with pytest.raises(Conflict):
                await accounts.removals.decide(1, str(old.id), True)
            stale = await accounts.removals.plan(1, first.id)
            async with sessions.begin() as session:
                draft = await session.get(StockRemovalDraft, str(stale.id))
                draft.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            with pytest.raises(Conflict):
                await accounts.removals.decide(1, str(stale.id), True)
            old = await accounts.removals.plan(1, first.id)
            newer = await accounts.removals.plan(1, first.id)
            with pytest.raises(Conflict):
                await accounts.removals.decide(1, str(old.id), True)
            await accounts.change_status(99, owner.id, owner.version, True, "Synthetic")
            with pytest.raises(AccessDenied):
                await accounts.removals.decide(1, str(newer.id), True)
            async with sessions() as session:
                assert await session.get(Batch, first.id) is not None

    asyncio.run(run())


def test_failed_manual_delete_rolls_back_event_ledger_and_keeps_confirmation():
    """A storage failure cannot erase the batch or falsely complete its confirmation."""

    async def run():
        async with database() as (accounts, sessions):
            await accounts.register(1, "Owner")
            item = await accounts.add(1, "one", BatchInput(name="Молоко"))
            plan = await accounts.removals.plan(1)
            async with sessions() as session:
                engine = session.bind.sync_engine

            def fail_delete(connection, cursor, statement, parameters, context, executemany):
                if statement.startswith("DELETE FROM batches"):
                    raise SQLAlchemyError("synthetic")

            event.listen(engine, "before_cursor_execute", fail_delete)
            try:
                with pytest.raises(SQLAlchemyError):
                    await accounts.removals.decide(1, str(plan.id), True)
            finally:
                event.remove(engine, "before_cursor_execute", fail_delete)
            async with sessions() as session:
                assert await session.get(Batch, item.id) is not None
                assert (
                    await session.scalar(select(func.count()).select_from(RemovedStockEvent)) == 0
                )
                assert (await session.get(StockRemovalDraft, str(plan.id))).status == "pending"

    asyncio.run(run())


def test_expiry_normalizes_receipt_names_and_keeps_unsupported_forms_honest():
    """Сопоставлять известные продукты с брендами без выдуманной оценки неизвестных форм."""
    today = date(2026, 11, 18)
    milk = estimate_name("Молоко «Бренд» пастеризованное 3,2% 950 мл", today)
    assert milk.rule_id == "milk" and milk.days == 7
    condensed = estimate_name("Молоко сгущённое с сахаром 380 г", today)
    assert condensed.rule_id == "condensed-milk" and condensed.days == 4
    smoked = estimate_name("Курица копчёная", today)
    assert smoked is None
    assert estimate_name("Сливочное масло 82,5%", today).days == 30


def test_manual_and_legacy_stock_get_automatic_badges_without_overwriting_dates():
    """Различать оценки, точные даты и неизвестные сроки без повторного изменения партий."""

    async def run():
        async with database() as (accounts, sessions):
            owner = await accounts.register(1, "Owner")
            new = await accounts.add(1, "manual", BatchInput(name="Молоко Бренд 3,2%"))
            assert new.expiry_source == "estimated" and new.expiry == current_date() + timedelta(
                days=7
            )
            assert "Примерно до" in stock_card(new)
            exact_date = current_date() + timedelta(days=2)
            known = await accounts.add(1, "known", BatchInput(name="Молоко", expiry=exact_date))
            async with sessions.begin() as session:
                legacy = Batch(
                    owner_id=owner.id,
                    event_key="synthetic-legacy",
                    name="Необычный соус",
                    expiry=None,
                    expiry_source="unknown",
                )
                session.add(legacy)
                await session.flush()
                identifier = legacy.id
            loaded = await accounts.stock_item(1, identifier)
            assert loaded.expiry is None and loaded.expiry_source == "unavailable"
            assert loaded.expiry_estimate is None
            assert "Срок не рассчитан" in stock_card(loaded)
            assert "Nebraska Extension" not in stock_card(loaded)
            again = await accounts.stock_item(1, identifier)
            assert again.expiry == loaded.expiry and again.version == loaded.version
            preserved = await accounts.stock_item(1, known.id)
            assert preserved.expiry == exact_date and preserved.expiry_source == "user"
            assert "Примерно до" not in stock_card(preserved)

    asyncio.run(run())


def test_delete_immediate_and_bulk_clear_confirmation_without_spam(recognition):
    """A cross removes one product immediately; full clearing still supports confirmation and cancel."""

    async def run():
        async with database() as (accounts, _):
            await accounts.register(1, "Owner")
            item = await accounts.add(1, "one", BatchInput(name="Молоко"))
            bot_session = Session(b"")
            bot = Bot("123456:TEST", session=bot_session)
            dispatcher = create_dispatcher(PhotoTrial(FakeRecognizer(recognition), None), accounts)
            await dispatcher.feed_update(bot, update(1, "Мой холодильник"))
            buttons = rich_buttons(bot_session.methods[-1])
            remove_button = next(
                button for button in buttons if button.callback_data.startswith("del:")
            )
            assert remove_button.text == "Удалить ❌" and remove_button.style == "link"
            assert "🟡" not in visible_text(bot_session.methods[-1])
            remove = remove_button.callback_data
            await dispatcher.feed_update(bot, callback(1, remove))
            assert isinstance(bot_session.methods[-1], EditMessageText)
            assert await accounts.inventory(1) == []
            assert "Холодильник пуст" in visible_text(bot_session.methods[-1])
            assert "Отменить удаление" not in visible_text(bot_session.methods[-1])
            await dispatcher.feed_update(bot, callback(1, remove, 1001))
            assert await accounts.inventory(1) == []
            await accounts.add(1, "two", BatchInput(name="Яблоки"))
            await dispatcher.feed_update(bot, callback(1, "clear:0", 1002))
            confirmation = bot_session.methods[-1]
            assert "Отменить удаление будет нельзя" in confirmation.text
            cancel = confirmation.reply_markup.inline_keyboard[1][0].callback_data
            await dispatcher.feed_update(bot, callback(1, cancel, 101))
            assert len(await accounts.inventory(1)) == 1
            await dispatcher.feed_update(bot, callback(1, "clear:0", 102))
            confirm = bot_session.methods[-1].reply_markup.inline_keyboard[0][0].callback_data
            await dispatcher.feed_update(bot, callback(1, confirm, 103))
            assert await accounts.inventory(1) == []
            assert "Холодильник пуст" in visible_text(bot_session.methods[-1])
            with pytest.raises(AccessDenied):
                await accounts.stock_item(1, item.id)
            assert (
                len(
                    [x for x in bot_session.methods if isinstance(x, SendMessage | SendRichMessage)]
                )
                == 1
            )

    asyncio.run(run())


def test_review_deadline_is_not_deleted_as_an_expired_product():
    """Сохранить партию и убрать старую искусственную дату проверки при чтении."""
    from ingredia.accounts.retention import StockRetention

    async def run():
        async with database() as (accounts, sessions):
            owner = await accounts.register(1, "Owner")
            async with sessions.begin() as session:
                row = Batch(
                    owner_id=owner.id,
                    event_key="review",
                    name="Неизвестная категория",
                    expiry=current_date() - timedelta(days=31),
                    expiry_source="review",
                )
                session.add(row)
                await session.flush()
                identifier = row.id
            assert await StockRetention(sessions).run_once() == 0
            item = await accounts.stock_item(1, identifier)
            assert "Срок не рассчитан" in stock_card(item)
            assert item.expiry is None and item.expiry_source == "unavailable"

    asyncio.run(run())


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="PostgreSQL not configured")
def test_concurrent_confirmations_delete_only_once_on_postgresql():
    """Competing confirmations serialize on the owner and cannot double-delete stock."""

    async def run():
        async with database(os.environ["TEST_DATABASE_URL"]) as (accounts, sessions):
            await accounts.register(1, "Owner")
            await accounts.add(1, "one", BatchInput(name="Молоко"))
            plan = await accounts.removals.plan(1)
            results = await asyncio.gather(
                accounts.removals.decide(1, str(plan.id), True),
                accounts.removals.decide(1, str(plan.id), True),
                return_exceptions=True,
            )
            assert sum(value == 1 for value in results) == 1
            assert sum(isinstance(value, Conflict) for value in results) == 1
            async with sessions() as session:
                assert (
                    await session.scalar(select(func.count()).select_from(RemovedStockEvent)) == 1
                )

    asyncio.run(run())


def test_clear_large_inventory_removes_every_page():
    """Clearing a large fridge covers products beyond the display and one SQL parameter batch."""

    async def run():
        async with database() as (accounts, sessions):
            owner = await accounts.register(1, "Owner")
            async with sessions.begin() as session:
                session.add_all(
                    Batch(
                        owner_id=owner.id,
                        event_key=f"seed-{index}",
                        name="Товар",
                        expiry=current_date() + timedelta(days=5),
                        expiry_source="user",
                    )
                    for index in range(501)
                )
            plan = await accounts.removals.plan(1)
            assert plan.count == 501
            assert await accounts.removals.decide(1, str(plan.id), True) == 501
            assert (await accounts.stock_page(1)).total == 0

    asyncio.run(run())


def test_unknown_preview_has_no_invented_date(recognition):
    """Неизвестная категория остаётся без даты и без требования ручного ввода.

    Args:
        recognition: Синтетический результат распознавания продуктов.
    """
    from ingredia.adapters.telegram.views import candidate_card

    product = recognition.products[0].model_copy(update={"name": "Необычный соус"})
    estimate = estimate_name(product.name, current_date())
    card = candidate_card(product, 1, estimate)
    assert estimate is None and "Срок не рассчитан" in card
    assert "Проверить до" not in card and "?" not in card


@pytest.mark.parametrize("postgres", [False, True])
def test_direct_delete_owner_version_block_and_replay(postgres):
    """Immediate deletion retains authorization, stale-version safety and no-resurrection rules."""
    if postgres and not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("PostgreSQL not configured")
    url = os.environ["TEST_DATABASE_URL"] if postgres else "sqlite+aiosqlite:///:memory:"

    async def run():
        async with database(url) as (accounts, sessions):
            owner = await accounts.register(1, "Owner")
            await accounts.register(2, "Other")
            await accounts.register(99, "Admin")
            item = await accounts.add(1, "first", BatchInput(name="Молоко"))
            assert not await accounts.removals.delete_one(2, item.id, item.version)
            with pytest.raises(Conflict):
                await accounts.removals.delete_one(1, item.id, item.version + 1)
            assert await accounts.removals.delete_one(1, item.id, item.version)
            assert not await accounts.removals.delete_one(1, item.id, item.version)
            with pytest.raises(Conflict):
                await accounts.add(1, "first", BatchInput(name="Replay"))
            another = await accounts.add(1, "other", BatchInput(name="Яблоки"))
            await accounts.change_status(99, owner.id, owner.version, True, "Synthetic")
            with pytest.raises(AccessDenied):
                await accounts.removals.delete_one(1, another.id, another.version)

    asyncio.run(run())


def test_compact_rich_rows_keep_inline_cross_and_product_names_as_data():
    """Вертикальные блоки сохраняют кнопки без таблицы и интерпретации названий как разметки."""
    from ingredia.accounts.models import BatchView, StockPage
    from ingredia.adapters.telegram.fridge_views import stock_content

    name = "<b>Сыр</b>"
    stock = StockPage(
        items=[
            BatchView(
                id="00000000-0000-0000-0000-000000000001",
                name=name,
                quantity=1,
                unit="kg",
                expiry=current_date() + timedelta(days=1),
                expiry_source="estimated",
            )
        ],
        total=1,
        page=0,
    )
    content = stock_content(stock)
    from aiogram.types import InputRichBlockParagraph

    assert all(isinstance(block, InputRichBlockParagraph) for block in content.blocks)
    product = content.blocks[3].text
    assert product[1].button.text == name
    assert "1 кг" in product[2] and "Примерно до" in product[2]
    assert "?" not in product[2] and "≈" not in product[2]
    assert product[3].button.text == "Удалить ❌"
    assert product[3].button.style == "link"
    assert product[3].button.callback_data.startswith("del:")
    assert content.skip_entity_detection
    rendered = content.model_dump_json()
    assert "🟡" not in rendered
    assert "Сортировка по сроку годности" in rendered


@pytest.mark.parametrize(
    ("name", "label"),
    [
        ("Сыр", "Сыр"),
        ("123456789012345678", "123456789012345678"),
        ("1234567890123456789", "12345678901234567…"),
        ("Молоко Бренд 3,2% 950 мл", "Молоко Бренд 3,2%…"),
        ("  Сыр\n\tтвёрдый  ", "Сыр твёрдый"),
    ],
)
def test_stock_list_limits_names_but_preserves_full_card_and_callbacks(name, label):
    """Сокращение подписи сохраняет полное название в карточке и ID действий.

    Args:
        name: Исходное название продукта.
        label: Ожидаемая подпись кнопки в списке.
    """
    from html import escape

    from ingredia.accounts.models import BatchView, StockPage
    from ingredia.adapters.telegram.fridge_views import stock_content, stock_details

    item = BatchView(
        id="00000000-0000-0000-0000-000000000001",
        name=name,
        quantity=None,
        unit=None,
        expiry=None,
        expiry_source="unknown",
    )
    content = stock_content(StockPage(items=[item], total=1, page=2))
    row = content.blocks[3].text
    product = row[1].button
    assert product.text == label
    assert product.callback_data == f"stock:{item.id}:2"
    assert row[3].button.callback_data == f"del:{item.id}:2:{item.version}"
    assert all(escape(line) in stock_details(item, "2").html for line in name.splitlines())
    assert item.name == name


@pytest.mark.parametrize("postgres", [False, True])
def test_unknown_purchase_and_legacy_review_stay_without_artificial_dates(recognition, postgres):
    """Неизвестные продукты и старые черновики не получают срок «до завтра».

    Args:
        recognition: Синтетическое наблюдение продуктов.
        postgres: Проверять поведение в изолированной схеме PostgreSQL вместо SQLite.
    """
    from ingredia.accounts.expiry import ExpiryEstimate
    from ingredia.storage.models import PurchaseDraft

    if postgres and not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("PostgreSQL not configured")
    url = os.environ["TEST_DATABASE_URL"] if postgres else "sqlite+aiosqlite:///:memory:"

    async def run():
        async with database(url) as (accounts, sessions):
            owner = await accounts.register(1, "Owner")
            other = await accounts.register(2, "Other")
            unknown = await accounts.add(1, "manual", BatchInput(name="Необычный соус"))
            assert unknown.expiry is None and unknown.expiry_source == "unavailable"
            product = recognition.products[0].model_copy(update={"name": "Необычный соус"})
            result = recognition.model_copy(update={"products": [product]})
            preview = await accounts.preview_purchase(1, "legacy-draft", result)
            assert preview.estimates == [None]
            legacy = ExpiryEstimate(
                expiry=current_date() + timedelta(days=1),
                reference_date=current_date(),
                days=1,
                rule_id="unclassified-review-v1",
                conditions="Прежняя дата проверки",
                source="ingredia:review-policy/v1",
            )
            async with sessions.begin() as session:
                draft = await session.get(PurchaseDraft, str(preview.id))
                draft.payload = {**draft.payload, "estimates": [legacy.model_dump(mode="json")]}
                old = Batch(
                    owner_id=owner.id,
                    event_key="legacy-stock",
                    name="Необычный соус",
                    expiry=current_date() - timedelta(days=31),
                    expiry_source="review",
                    expiry_estimate=legacy.model_dump(mode="json"),
                )
                foreign = Batch(
                    owner_id=other.id,
                    event_key="foreign-stock",
                    name="Необычный соус",
                    expiry=legacy.expiry,
                    expiry_source="review",
                )
                session.add_all([old, foreign])
                await session.flush()
                old_id, foreign_id = old.id, foreign.id
            assert await accounts.decide_purchase(1, str(preview.id), True) == 1
            stock = await accounts.stock_page(1)
            assert stock.total == 3
            assert all(row.expiry is None and row.expiry_estimate is None for row in stock.items)
            assert all(row.expiry_source == "unavailable" for row in stock.items)
            versions = {row.id: row.version for row in stock.items}
            assert versions[old_id] == 2
            assert {row.id: row.version for row in (await accounts.stock_page(1)).items} == versions
            async with sessions() as session:
                untouched = await session.get(Batch, foreign_id)
                assert untouched.expiry_source == "review" and untouched.expiry == legacy.expiry

    asyncio.run(run())
