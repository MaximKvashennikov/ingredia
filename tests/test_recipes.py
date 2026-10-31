"""Recipes and favorites with real private persistence and fake cloud adapters."""

import asyncio
import json
import os
from datetime import date, timedelta

import httpx
import pytest
from aiogram import Bot
from aiogram.methods import EditMessageText, SendMessage
from pydantic import SecretStr, ValidationError
from test_accounts import database
from test_navigation import Session, callback, update
from test_provider_selection import settings
from test_telegram import FakeRecognizer

from ingredia.accounts.models import AccessDenied, BatchInput, BatchView
from ingredia.adapters.telegram import create_dispatcher
from ingredia.providers import create_recognizers
from ingredia.recipes.availability import check_ingredient
from ingredia.recipes.models import Availability, Ingredient, RecipeSuggestions
from ingredia.recipes.service import RecipeService
from ingredia.recognition.errors import FailureCode, RecognitionFailure
from ingredia.recognition.policy import TrialAdmission
from ingredia.recognition.service import PhotoTrial


def suggestions():
    """Return one synthetic recipe with no unlisted pantry assumptions."""
    return RecipeSuggestions.model_validate(
        {
            "recipes": [
                {
                    "title": "Молоко с солью",
                    "servings": 1,
                    "minutes": 2,
                    "ingredients": [
                        {"name": "Молоко", "quantity": 200, "unit": "ml"},
                        {"name": "Соль", "quantity": 1, "unit": "g"},
                    ],
                    "steps": ["Налейте молоко в чашку.", "Добавьте соль и перемешайте."],
                }
            ]
        }
    )


class Generator:
    """Record non-personal stock input and return a bounded known proposal."""

    source = "AI · fake provider"

    def __init__(self):
        """Initialize synthetic call history."""
        self.calls = []

    async def suggest(self, stock):
        """Return proposals without reading accounts or changing inventory."""
        self.calls.append(stock)
        return suggestions()


def make_service(sessions, generator, today=date.today):
    """Disable elapsed cooldown in deterministic tests while keeping duplicate protection."""
    return RecipeService(sessions, generator, TrialAdmission(None, 0, lambda: 0), today)


@pytest.mark.parametrize("postgres", [False, True])
def test_recipe_favorite_snapshot_persistence_and_foreign_access(postgres):
    """Saved snapshots survive service recreation; repeats and foreign actions cannot alter stock."""
    if postgres and not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("PostgreSQL not configured")
    url = os.environ["TEST_DATABASE_URL"] if postgres else "sqlite+aiosqlite:///:memory:"

    async def run():
        async with database(url) as (accounts, sessions):
            await accounts.register(1, "Owner")
            await accounts.register(2, "Other")
            await accounts.add(1, "milk", BatchInput(name="Молоко", quantity=1, unit="l"))
            generator = Generator()
            recipes = make_service(sessions, generator)
            before = await accounts.inventory(1)
            views = await recipes.generate(1, 10)
            view = views[0]
            assert view.ingredients[0].status == Availability.AVAILABLE
            assert view.ingredients[1].status == Availability.MISSING
            assert "срок неизвестен" in view.ingredients[0].note
            await recipes.favorite(1, view.id, True)
            await recipes.favorite(1, view.id, True)
            restarted = make_service(sessions, generator)
            assert await restarted.favorites(1) == [(view.id, view.snapshot.proposal.title)]
            assert (await restarted.get(1, view.id)).favorite
            assert len(generator.calls) == 1
            for action in [restarted.get(2, view.id), restarted.favorite(2, view.id, False)]:
                with pytest.raises(AccessDenied):
                    await action
            assert await restarted.favorites(2) == []
            await restarted.generate(1, 11)
            assert (await restarted.get(1, view.id)).favorite
            await restarted.favorite(1, view.id, False)
            assert await restarted.favorites(1) == []
            assert await accounts.inventory(1) == before

    asyncio.run(run())


def test_expired_estimates_excluded_and_full_inventory_read():
    """The generator sees beyond the first fridge page and never receives expired batches."""

    async def run():
        async with database() as (accounts, sessions):
            await accounts.register(1, "Owner")
            for index in range(9):
                await accounts.add(1, str(index), BatchInput(name=f"Продукт {index}"))
            await accounts.add(
                1,
                "old",
                BatchInput(
                    name="Старое молоко",
                    expiry=date.today() - timedelta(days=1),
                ),
            )
            generator = Generator()
            recipes = make_service(sessions, generator)
            await recipes.generate(1, 100)
            assert len(generator.calls[0]) == 9
            assert all(row.name != "Старое молоко" for row in generator.calls[0])
            with pytest.raises(RecognitionFailure) as duplicate:
                await recipes.generate(1, 100)
            assert duplicate.value.code == FailureCode.DUPLICATE
            assert len(generator.calls) == 1

    asyncio.run(run())


def test_generator_failure_preserves_saved_cards_and_inventory():
    """A provider failure cannot clear favorites or partially persist a generation."""

    class Failing(Generator):
        """Simulate a safe free-tier provider rejection."""

        async def suggest(self, stock):
            """Reject without a fallback or side effect."""
            raise RecognitionFailure(FailureCode.QUOTA)

    async def run():
        async with database() as (accounts, sessions):
            await accounts.register(1, "Owner")
            await accounts.add(1, "milk", BatchInput(name="Молоко"))
            good = make_service(sessions, Generator())
            view = (await good.generate(1, 1))[0]
            await good.favorite(1, view.id, True)
            before = await accounts.inventory(1)
            bad = make_service(sessions, Failing())
            with pytest.raises(RecognitionFailure):
                await bad.generate(1, 2)
            assert (await good.get(1, view.id)).favorite
            assert await accounts.inventory(1) == before

    asyncio.run(run())


def test_account_blocked_during_generation_cannot_publish_snapshots():
    """Rechecking authority after an external await rejects a newly blocked account."""

    async def run():
        async with database() as (accounts, sessions):
            await accounts.register(99, "Admin")
            owner = await accounts.register(1, "Owner")
            await accounts.add(1, "milk", BatchInput(name="Молоко"))

            class Blocking(Generator):
                """Change account status while the synthetic AI request is in flight."""

                async def suggest(self, stock):
                    """Model the administrative race before returning valid proposals."""
                    await accounts.change_status(99, owner.id, owner.version, True, "Synthetic")
                    return suggestions()

            with pytest.raises(AccessDenied):
                await make_service(sessions, Blocking()).generate(1, 1)

    asyncio.run(run())


@pytest.mark.parametrize("expiry_source", ["user", "estimated"])
def test_expired_dates_are_unavailable_for_any_source(expiry_source):
    """An estimated past date cannot be promoted to usable stock."""
    row = BatchView(
        id="synthetic",
        name="Молоко",
        quantity=2,
        unit="l",
        expiry=date(2026, 10, 29),
        expiry_source=expiry_source,
    )
    result = check_ingredient(
        Ingredient(name="Молоко", quantity=100, unit="ml"),
        [row],
        date(2026, 10, 30),
    )
    assert result.status == Availability.MISSING
    assert "истёк" in result.note


def test_unknown_quantity_units_and_estimates_are_explicit():
    """Unknown quantities cannot be asserted sufficient and estimated dates stay labeled."""
    item = Ingredient(name="Молоко", quantity=200, unit="ml")
    row = BatchView(
        id="synthetic",
        name="Молоко",
        quantity=None,
        unit=None,
        expiry=date(2026, 11, 5),
        expiry_source="estimated",
    )
    result = check_ingredient(item, [row], date(2026, 10, 30))
    assert result.status == Availability.CHECK
    assert result.confirmed_expiry is None and "срок по оценке" in result.note


@pytest.mark.parametrize("provider", ["groq", "zai"])
def test_recipe_adapter_contract_and_validation(provider):
    """Both selected providers obey the same port without leaking account identifiers."""

    async def run():
        calls = []

        def handle(request):
            payload = json.loads(request.content)
            calls.append(payload)
            context = payload["messages"][1]["content"]
            assert "secret-owner" not in context and "telegram" not in context
            assert "Молоко" in context
            if provider == "groq":
                assert payload["response_format"]["json_schema"]["name"] == "recipe_suggestions"
            else:
                assert payload["model"] == "glm-4.7-flash"
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": suggestions().model_dump_json()},
                        }
                    ]
                },
            )

        key = "groq" if provider == "groq" else "zai"
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            ports = create_recognizers(settings(provider, **{key: SecretStr("fake-key")}), client)
            stock = [
                BatchView(
                    id="secret-owner",
                    name="Молоко",
                    quantity=1,
                    unit="l",
                    expiry=None,
                    expiry_source="unknown",
                )
            ]
            assert await ports.recipes.suggest(stock) == suggestions()
        assert len(calls) == 1

    asyncio.run(run())


def test_recipe_menu_favorite_buttons_and_reopen_without_generation(recognition):
    """Menu routes produce readable cards, persist favorites and edit repeated actions."""

    async def run():
        async with database() as (accounts, sessions):
            await accounts.register(1, "Owner")
            await accounts.add(1, "milk", BatchInput(name="Молоко", quantity=1, unit="l"))
            generator = Generator()
            recipes = make_service(sessions, generator)
            session = Session(b"")
            bot = Bot("123456:TEST", session=session)
            dispatcher = create_dispatcher(
                PhotoTrial(FakeRecognizer(recognition), None), accounts, recipes
            )
            await dispatcher.feed_update(bot, update(1, "Что приготовить", 10))
            card = session.methods[-1]
            assert isinstance(card, SendMessage)
            assert "Как приготовить" in card.text and "Нужно дополнить" in card.text
            assert "AI" in card.text and "Соль" in card.text
            save = card.reply_markup.inline_keyboard[0][0].callback_data
            await dispatcher.feed_update(bot, callback(1, save))
            assert isinstance(session.methods[-1], EditMessageText)
            assert "В избранном" in session.methods[-1].reply_markup.inline_keyboard[0][0].text
            await dispatcher.feed_update(bot, callback(1, save, 101))
            await dispatcher.feed_update(bot, update(1, "Избранное", 11))
            open_card = session.methods[-1].reply_markup.inline_keyboard[0][0].callback_data
            await dispatcher.feed_update(bot, callback(1, open_card, 102))
            assert "Молоко с солью" in session.methods[-1].text
            assert len(generator.calls) == 1

    asyncio.run(run())


def test_duplicate_ingredients_rejected():
    """A recipe cannot count the same stock twice by repeating the ingredient."""
    data = suggestions().model_dump()
    data["recipes"][0]["ingredients"].append(data["recipes"][0]["ingredients"][0])
    with pytest.raises(ValidationError):
        RecipeSuggestions.model_validate(data)


def test_blocked_user_old_recipe_buttons_are_denied_without_ai(recognition):
    """Old recipe and favorite callbacks receive a denial without loading private cards."""

    async def run():
        async with database() as (accounts, sessions):
            await accounts.register(99, "Admin")
            owner = await accounts.register(1, "Owner")
            await accounts.add(1, "milk", BatchInput(name="Молоко"))
            generator = Generator()
            recipes = make_service(sessions, generator)
            session = Session(b"")
            bot = Bot("123456:TEST", session=session)
            dispatcher = create_dispatcher(
                PhotoTrial(FakeRecognizer(recognition), None), accounts, recipes
            )
            await accounts.change_status(99, owner.id, owner.version, True, "Synthetic")
            await dispatcher.feed_update(bot, callback(1, "recipes:new"))
            assert "заблокирован" in session.methods[-1].text
            await dispatcher.feed_update(bot, callback(1, "favorites:0", 101))
            assert "недоступно" in session.methods[-1].text
            assert not generator.calls
            assert not any(isinstance(method, EditMessageText) for method in session.methods)

    asyncio.run(run())
