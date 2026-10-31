"""Create explicit asynchronous database resources without import side effects."""

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from ingredia.accounts.service import AccountService


def create_database(url: str, administrators: frozenset[int]) -> tuple[AsyncEngine, AccountService]:
    """Build a private engine and application service; migrations are separate."""
    engine = create_async_engine(url, echo=False, hide_parameters=True, pool_pre_ping=True)
    return engine, AccountService(
        async_sessionmaker(engine, expire_on_commit=False), administrators
    )
