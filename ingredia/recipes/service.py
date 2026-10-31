"""Generate bounded suggestions and store owner-bound recipe snapshots."""

import asyncio
from collections.abc import Callable
from datetime import date
from time import monotonic
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ingredia.accounts.access import active_account
from ingredia.accounts.models import AccessDenied, BatchView
from ingredia.accounts.retention import purge_owner
from ingredia.clock import current_date
from ingredia.recipes.availability import check_ingredient
from ingredia.recipes.models import (
    Availability,
    RecipeSnapshot,
    RecipeSuggestions,
    RecipeView,
)
from ingredia.recognition.errors import FailureCode, RecognitionFailure
from ingredia.recognition.policy import TrialAdmission
from ingredia.storage.models import Batch, Recipe

MAX_STOCK = 60


class RecipeGenerator(Protocol):
    """Port for cloud recipe generation, independent of Telegram and SQLAlchemy."""

    source: str

    async def suggest(self, stock: list[BatchView]) -> RecipeSuggestions:
        """Return validated dish proposals without availability claims or stock mutations."""
        ...


class RecipeService:
    """Recheck active ownership around external calls and on every saved-card action."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        generator: RecipeGenerator,
        admission: TrialAdmission | None = None,
        today: Callable[[], date] = current_date,
    ) -> None:
        """Inject persistence, a selected provider and bounded process-local admission."""
        self._sessions = sessions
        self._generator = generator
        self._admission = admission or TrialAdmission(None, 15, monotonic)
        self._today = today

    async def _stock(self, actor: int, bounded: bool = True) -> list[BatchView]:
        async with self._sessions.begin() as session:
            owner = await active_account(session, actor)
            await purge_owner(session, owner.id, self._today())
            rows = await session.scalars(
                select(Batch)
                .where(Batch.owner_id == owner.id)
                .order_by(Batch.expiry.is_(None), Batch.expiry, Batch.id)
                .limit(MAX_STOCK + 1 if bounded else None)
            )
            stock = [BatchView.model_validate(row) for row in rows]
        if bounded and len(stock) > MAX_STOCK:
            raise RecognitionFailure(FailureCode.INVALID_RESPONSE)
        return stock

    def _view(self, row: Recipe, stock: list[BatchView]) -> RecipeView:
        snapshot = RecipeSnapshot.model_validate(row.payload)
        return RecipeView(
            id=row.id,
            snapshot=snapshot,
            favorite=row.favorite,
            ingredients=[
                check_ingredient(item, stock, self._today())
                for item in snapshot.proposal.ingredients
            ],
        )

    async def generate(self, actor: int, event_id: int) -> list[RecipeView]:
        """Use current non-expired stock and persist snapshots after a second access check."""
        stock = await self._stock(actor)
        usable = [row for row in stock if row.expiry is None or row.expiry >= self._today()]
        if not usable:
            return []
        try:
            with self._admission.admit(actor, event_id):
                async with asyncio.timeout(65):
                    proposals = await self._generator.suggest(usable)
        except TimeoutError:
            raise RecognitionFailure(FailureCode.TIMEOUT) from None
        current = await self._stock(actor)
        async with self._sessions.begin() as session:
            owner = await active_account(session, actor)
            await session.execute(
                delete(Recipe).where(Recipe.owner_id == owner.id, Recipe.favorite.is_(False))
            )
            rows = [
                Recipe(
                    owner_id=owner.id,
                    payload=RecipeSnapshot(proposal=item, source=self._generator.source).model_dump(
                        mode="json"
                    ),
                )
                for item in proposals.recipes
            ]
            session.add_all(rows)
            await session.flush()
            views = [self._view(row, current) for row in rows]

        def rank(view: RecipeView) -> tuple[int, int, date]:
            return (
                sum(item.status == Availability.MISSING for item in view.ingredients),
                sum(item.status == Availability.CHECK for item in view.ingredients),
                min(
                    (
                        item.confirmed_expiry
                        for item in view.ingredients
                        if item.confirmed_expiry is not None
                    ),
                    default=date.max,
                ),
            )

        return sorted(views, key=rank)

    async def get(self, actor: int, identifier: str) -> RecipeView:
        """Open an own saved snapshot without calling the generator again."""
        stock = await self._stock(actor, bounded=False)
        async with self._sessions.begin() as session:
            owner = await active_account(session, actor)
            row = await session.scalar(
                select(Recipe).where(Recipe.id == identifier, Recipe.owner_id == owner.id)
            )
            if row is None:
                raise AccessDenied
            return self._view(row, stock)

    async def favorite(self, actor: int, identifier: str, value: bool) -> None:
        """Set a desired favorite state idempotently after current owner verification."""
        async with self._sessions.begin() as session:
            owner = await active_account(session, actor)
            row = await session.scalar(
                select(Recipe)
                .where(Recipe.id == identifier, Recipe.owner_id == owner.id)
                .with_for_update()
            )
            if row is None:
                raise AccessDenied
            row.favorite = value

    async def favorites(self, actor: int, page: int = 0) -> list[tuple[str, str]]:
        """Return only bounded own titles; snapshots are read on explicit opening."""
        if not 0 <= page <= 100000:
            raise ValueError("Invalid favorites page")
        async with self._sessions.begin() as session:
            owner = await active_account(session, actor)
            rows = await session.scalars(
                select(Recipe)
                .where(Recipe.owner_id == owner.id, Recipe.favorite.is_(True))
                .order_by(Recipe.created_at, Recipe.id)
                .offset(page * 6)
                .limit(7)
            )
            return [
                (row.id, RecipeSnapshot.model_validate(row.payload).proposal.title) for row in rows
            ]
