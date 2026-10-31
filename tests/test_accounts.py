"""Persistence behavior against isolated SQLite and optional PostgreSQL schemas."""

import asyncio
import os
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ingredia.accounts.models import AccessDenied, BatchInput, Conflict
from ingredia.accounts.service import AccountService
from ingredia.storage.models import Audit, Base


@asynccontextmanager
async def database(url="sqlite+aiosqlite:///:memory:", admins=frozenset({99})):
    """Use a random PostgreSQL schema; never delete an existing database."""
    engine = create_async_engine(url, hide_parameters=True)
    schema = "test_" + uuid4().hex
    postgres = url.startswith("postgresql")
    try:
        async with engine.begin() as connection:
            if postgres:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                connection = await connection.execution_options(schema_translate_map={None: schema})
            await connection.run_sync(Base.metadata.create_all)
        bind = engine.execution_options(schema_translate_map={None: schema}) if postgres else engine
        sessions = async_sessionmaker(bind, expire_on_commit=False)
        yield AccountService(sessions, admins), sessions
    finally:
        if postgres:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


async def account_scenario(url):
    """Check identity, isolation, redelivery, stale versions and audit."""
    async with database(url) as (service, sessions):
        one = await service.register(1, "Same")
        two = await service.register(2, "Same")
        assert one.id != two.id
        assert (await service.register(1, "Same")).id == one.id
        data = BatchInput(name="Молоко", quantity="2", unit="l", expiry="2026-11-05")
        first = await service.add(1, "event1", data)
        assert (await service.add(1, "event1", data)).id == first.id
        assert (await service.add(1, "event2", data)).id != first.id
        assert len(await service.inventory(1)) == 2
        assert await service.inventory(2) == []
        with pytest.raises(AccessDenied):
            await service.users(1)
        await service.register(99, "Admin")
        await service.change_status(99, one.id, one.version, True, "Test reason")
        with pytest.raises(AccessDenied):
            await service.profile(1)
        with pytest.raises(AccessDenied):
            await service.add(1, "event3", data)
        with pytest.raises(Conflict):
            await service.change_status(99, one.id, one.version, False, "Stale")
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(Audit)) == 1
        current = await service.admin_target(99, one.id)
        await service.change_status(99, one.id, current.version, False, "Unblock")
        assert len(await service.inventory(1)) == 2


def test_account_stock_and_administration():
    """Verify behavior with isolated local persistence."""
    asyncio.run(account_scenario("sqlite+aiosqlite:///:memory:"))


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="PostgreSQL test server not configured"
)
def test_postgresql_account_stock_and_administration():
    """Repeat transaction checks on real PostgreSQL when configured."""
    asyncio.run(account_scenario(os.environ["TEST_DATABASE_URL"]))


@pytest.mark.parametrize(
    "values",
    [
        {"name": "x", "quantity": "-1", "unit": "l"},
        {"name": "x", "quantity": "2"},
        {"name": "x", "unit": "l"},
        {"name": "x", "quantity": "NaN", "unit": "l"},
        {"name": "x", "quantity": "1", "unit": "invalid"},
    ],
)
def test_invalid_quantities(values):
    """Incomplete and invalid amounts cannot enter stock."""
    with pytest.raises(ValidationError):
        BatchInput.model_validate(values)


def test_default_deny_and_protected_administrator():
    """An empty list grants no rights and administrators cannot be blocked."""

    async def run():
        async with database(admins=frozenset()) as (service, _):
            await service.register(99, "Admin")
            with pytest.raises(AccessDenied):
                await service.users(99)
        async with database() as (service, _):
            admin = await service.register(99, "Admin")
            with pytest.raises(AccessDenied):
                await service.change_status(99, admin.id, 1, True, "Self block")

    asyncio.run(run())


def test_audit_failure_rolls_back_status():
    """A failed audit write cannot leave an unaudited block committed."""
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    def fail_audit(session, flush_context, instances):
        if any(isinstance(row, Audit) for row in session.new):
            raise RuntimeError("Synthetic audit storage failure")

    async def run():
        async with database() as (service, _):
            target = await service.register(1, "Target")
            await service.register(99, "Admin")
            event.listen(Session, "before_flush", fail_audit)
            try:
                with pytest.raises(RuntimeError, match="Synthetic audit"):
                    await service.change_status(99, target.id, 1, True, "Reason")
            finally:
                event.remove(Session, "before_flush", fail_audit)
            assert not (await service.profile(1)).blocked

    asyncio.run(run())


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="PostgreSQL server not configured")
def test_postgresql_concurrent_identity_and_duplicate_purchase():
    """Database locks and unique constraints protect concurrent redelivery."""

    async def run():
        async with database(os.environ["TEST_DATABASE_URL"]) as (service, _):
            users = await asyncio.gather(*(service.register(1, "Same") for _ in range(5)))
            assert len({user.id for user in users}) == 1
            rows = await asyncio.gather(
                *(service.add(1, "same", BatchInput(name="Milk")) for _ in range(5))
            )
            assert len({row.id for row in rows}) == 1
            assert len(await service.inventory(1)) == 1

    asyncio.run(run())
