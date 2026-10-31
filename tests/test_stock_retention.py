"""Strict expiry cutoff, physical deletion and event deduplication with no AI calls."""

import asyncio
import os
from datetime import date, timedelta

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import SQLAlchemyError
from test_accounts import database

from ingredia.accounts.models import AccessDenied, BatchInput, Conflict
from ingredia.accounts.retention import StockRetention
from ingredia.accounts.service import AccountService
from ingredia.recipes.models import RecipeSnapshot
from ingredia.storage.models import Account, Batch, Recipe, RemovedStockEvent

TODAY = date(2026, 10, 31)


async def add_stock(accounts, sessions, actor, event_key, expiry, source="user"):
    """Seed synthetic batches with explicit expiry provenance."""
    row = await accounts.add(actor, event_key, BatchInput(name=event_key, expiry=expiry))
    async with sessions.begin() as session:
        batch = await session.get(Batch, row.id)
        batch.expiry_source = source
    return row


@pytest.mark.parametrize("postgres", [False, True])
def test_strict_30_day_boundary_unknown_dates_and_deduplication(postgres):
    """Delete at 31 days, retain exactly 30 days and prevent re-creation on redelivery."""
    if postgres and not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("PostgreSQL not configured")
    url = os.environ["TEST_DATABASE_URL"] if postgres else "sqlite+aiosqlite:///:memory:"

    async def run():
        async with database(url) as (_, sessions):
            accounts = AccountService(sessions, frozenset({99}), today=lambda: TODAY)
            await accounts.register(1, "Owner")
            for days, source in [(31, "confirmed"), (32, "estimated"), (30, "user"), (1, "user")]:
                await add_stock(
                    accounts,
                    sessions,
                    1,
                    f"expired-{days}",
                    TODAY - timedelta(days=days),
                    source,
                )
            await add_stock(accounts, sessions, 1, "unknown", None, "unknown")
            await add_stock(accounts, sessions, 1, "future", TODAY + timedelta(days=10))
            cleanup = StockRetention(sessions, today=lambda: TODAY)
            assert await cleanup.run_once() == 2
            assert await cleanup.run_once() == 0
            names = {row.name for row in await accounts.inventory(1)}
            assert names == {"expired-30", "expired-1", "unknown", "future"}
            with pytest.raises(Conflict):
                await accounts.add(1, "expired-31", BatchInput(name="Replay"))
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(Batch)) == 4
                assert (
                    await session.scalar(select(func.count()).select_from(RemovedStockEvent)) == 2
                )

    asyncio.run(run())


def test_owner_read_cleanup_commits_even_for_deleted_card():
    """A stale card cannot roll back deletion or purge another owner's products."""

    async def run():
        async with database() as (_, sessions):
            accounts = AccountService(sessions, frozenset({99}), today=lambda: TODAY)
            await accounts.register(1, "Owner")
            await accounts.register(2, "Other")
            stale = await add_stock(accounts, sessions, 1, "stale", TODAY - timedelta(days=31))
            foreign = await add_stock(accounts, sessions, 2, "foreign", TODAY - timedelta(days=31))
            with pytest.raises(AccessDenied):
                await accounts.stock_item(1, stale.id)
            async with sessions() as session:
                assert await session.get(Batch, stale.id) is None
                assert await session.get(Batch, foreign.id) is not None
                assert (
                    await session.scalar(select(func.count()).select_from(RemovedStockEvent)) == 1
                )
            assert (await accounts.stock_page(1)).total == 0

    asyncio.run(run())


def test_cleanup_preserves_users_favorites_and_cleans_blocked_owners():
    """Background maintenance is system-scoped and never deletes account or recipe data."""
    from test_recipes import suggestions

    async def run():
        async with database() as (_, sessions):
            accounts = AccountService(sessions, frozenset({99}), today=lambda: TODAY)
            await accounts.register(99, "Admin")
            owner = await accounts.register(1, "Owner")
            await add_stock(accounts, sessions, 1, "stale", TODAY - timedelta(days=31))
            async with sessions.begin() as session:
                favorite = Recipe(
                    owner_id=owner.id,
                    favorite=True,
                    payload=RecipeSnapshot(
                        proposal=suggestions().recipes[0],
                        source="AI synthetic",
                    ).model_dump(mode="json"),
                )
                session.add(favorite)
                await session.flush()
                identifier = favorite.id
            await accounts.change_status(99, owner.id, owner.version, True, "Synthetic")
            assert await StockRetention(sessions, today=lambda: TODAY).run_once() == 1
            async with sessions() as session:
                assert await session.get(Account, owner.id) is not None
                assert (await session.get(Recipe, identifier)).favorite

    asyncio.run(run())


def test_failed_delete_rolls_back_ledger_and_batch():
    """A transaction cannot retain a tombstone while leaving an undeleted stock row."""

    async def run():
        async with database() as (_, sessions):
            accounts = AccountService(sessions, frozenset(), today=lambda: TODAY)
            await accounts.register(1, "Owner")
            row = await add_stock(accounts, sessions, 1, "stale", TODAY - timedelta(days=31))
            async with sessions() as session:
                engine = session.bind.sync_engine

            def fail_delete(connection, cursor, statement, parameters, context, executemany):
                if statement.startswith("DELETE FROM batches"):
                    raise SQLAlchemyError("Synthetic delete failure")

            event.listen(engine, "before_cursor_execute", fail_delete)
            try:
                with pytest.raises(SQLAlchemyError):
                    await StockRetention(sessions, today=lambda: TODAY).run_once()
            finally:
                event.remove(engine, "before_cursor_execute", fail_delete)
            async with sessions() as session:
                assert await session.get(Batch, row.id) is not None
                assert (
                    await session.scalar(select(func.count()).select_from(RemovedStockEvent)) == 0
                )

    asyncio.run(run())


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="PostgreSQL not configured")
def test_concurrent_read_and_maintenance_have_one_atomic_deletion():
    """Concurrent cleanup paths serialize on the owner and do not duplicate tombstones."""

    async def run():
        async with database(os.environ["TEST_DATABASE_URL"]) as (_, sessions):
            accounts = AccountService(sessions, frozenset(), today=lambda: TODAY)
            await accounts.register(1, "Owner")
            await add_stock(accounts, sessions, 1, "stale", TODAY - timedelta(days=31))
            cleanup = StockRetention(sessions, today=lambda: TODAY)
            await asyncio.gather(cleanup.run_once(), cleanup.run_once(), accounts.stock_page(1))
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(Batch)) == 0
                assert (
                    await session.scalar(select(func.count()).select_from(RemovedStockEvent)) == 1
                )

    asyncio.run(run())


def test_periodic_cleanup_recovers_after_failure_and_is_cancellable(caplog):
    """A transient database error is logged safely and does not end the maintenance task."""

    async def run():
        cleanup = StockRetention(None)
        completed = asyncio.Event()
        attempts = 0

        async def perform():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise SQLAlchemyError("synthetic-private-connection")
            completed.set()
            return 0

        cleanup.run_once = perform
        task = asyncio.create_task(cleanup.run_periodically(interval_seconds=0.001))
        try:
            await asyncio.wait_for(completed.wait(), timeout=1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert task.cancelled() and attempts >= 2
        assert "SQLAlchemyError" in caplog.text
        assert "synthetic-private-connection" not in caplog.text

    asyncio.run(run())


def test_runtime_owns_initial_cleanup_and_cancels_background_task(monkeypatch):
    """Startup removes eligible rows and shutdown cancels maintenance before disposing storage."""
    from types import SimpleNamespace

    from pydantic import SecretStr
    from test_provider_selection import settings

    import ingredia.runtime as runtime
    from ingredia.clock import current_date
    from ingredia.settings.database import DatabaseSettings

    async def run():
        async with database() as (accounts, sessions):
            await accounts.register(1, "Owner")
            row = await accounts.add(
                1,
                "old",
                BatchInput(name="Old", expiry=current_date() - timedelta(days=31)),
            )
            engine = sessions.kw["bind"]
            started = asyncio.Event()

            class FakeSession:
                async def close(self):
                    pass

            class FakeBot:
                def __init__(self, **kwargs):
                    self.session = FakeSession()

                async def get_me(self):
                    return SimpleNamespace(username="trial_bot")

                async def get_webhook_info(self):
                    return SimpleNamespace(url="")

            class Dispatcher:
                async def start_polling(self, *args, **kwargs):
                    started.set()
                    await asyncio.Event().wait()

            monkeypatch.setattr(runtime, "Bot", FakeBot)
            monkeypatch.setattr(runtime, "create_database", lambda url, admins: (engine, accounts))
            monkeypatch.setattr(runtime, "create_dispatcher", lambda *args: Dispatcher())
            config = settings("groq", groq=SecretStr("fake-key"))
            config.database = DatabaseSettings(url=SecretStr("synthetic-url"))
            async with runtime.run_photo_trial(config) as active:
                await asyncio.wait_for(started.wait(), timeout=2)
                assert active.retention_task is not None and not active.retention_task.done()
                async with sessions() as session:
                    assert await session.get(Batch, row.id) is None
            assert active.retention_task.cancelled()

    asyncio.run(run())
