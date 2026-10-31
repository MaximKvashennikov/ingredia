"""Transactional private inventory and default-deny user administration."""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from ingredia.accounts.access import active_account
from ingredia.accounts.expiry import estimate_expiry
from ingredia.accounts.models import (
    AccessDenied,
    AccountFilter,
    AccountPage,
    AccountView,
    BatchInput,
    BatchView,
    Conflict,
    StockPage,
)
from ingredia.accounts.purchases import PurchaseContents, PurchasePreview, load_contents, to_stock
from ingredia.accounts.retention import purge_owner
from ingredia.clock import current_date
from ingredia.recognition.models import PhotoRecognition
from ingredia.storage.models import Account, Audit, Batch, PurchaseDraft, RemovedStockEvent


class AccountService:
    """Apply authorization inside transactions, independently of Telegram UI."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        admins: frozenset[int],
        today: Callable[[], date] = current_date,
    ) -> None:
        """Inject persistence and trusted administrative identities."""
        self._sessions = sessions
        self._admins = admins
        self._today = today

    async def register(self, telegram_id: int, name: str) -> AccountView:
        """Resolve identity atomically using the Telegram uniqueness constraint."""
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        async with self._sessions.begin() as session:
            dialect = session.get_bind().dialect.name
            statement = pg_insert(Account) if dialect == "postgresql" else sqlite_insert(Account)
            await session.execute(
                statement.values(telegram_id=telegram_id, name=name[:128]).on_conflict_do_nothing(
                    index_elements=["telegram_id"]
                )
            )
            return AccountView.model_validate(await active_account(session, telegram_id))

    async def profile(self, telegram_id: int) -> AccountView:
        """Read only the verified sender's own account."""
        async with self._sessions.begin() as session:
            return AccountView.model_validate(await active_account(session, telegram_id))

    async def inventory(self, telegram_id: int, page: int = 0) -> list[BatchView]:
        """Read the items of a compact private inventory page."""
        return (await self.stock_page(telegram_id, page)).items

    async def stock_page(self, actor: int, page: int = 0) -> StockPage:
        """Read six batches with exact page bounds, after active owner verification."""
        if not 0 <= page <= 100000:
            raise ValueError("Invalid stock page")
        async with self._sessions.begin() as session:
            owner = await active_account(session, actor)
            await purge_owner(session, owner.id, self._today())
            total = (
                await session.scalar(
                    select(func.count()).select_from(Batch).where(Batch.owner_id == owner.id)
                )
                or 0
            )
            page = min(page, max(0, (total - 1) // 6))
            rows = await session.scalars(
                select(Batch)
                .where(Batch.owner_id == owner.id)
                .order_by(Batch.name, Batch.id)
                .offset(page * 6)
                .limit(6)
            )
            return StockPage(
                items=[BatchView.model_validate(row) for row in rows],
                total=total,
                page=page,
            )

    async def add(self, telegram_id: int, event_key: str, data: BatchInput) -> BatchView:
        """Save manual stock once; the actor lock serializes duplicate submissions."""
        async with self._sessions.begin() as session:
            owner = await active_account(session, telegram_id)
            key = f"{owner.id}:{event_key}"
            if await session.get(RemovedStockEvent, key) is not None:
                raise Conflict
            existing = await session.scalar(select(Batch).where(Batch.event_key == key))
            if existing is not None:
                return BatchView.model_validate(existing)
            row = Batch(
                owner_id=owner.id,
                event_key=key,
                name=data.name,
                quantity=data.quantity,
                unit=data.unit,
                expiry=data.expiry,
                expiry_source="user" if data.expiry else "unknown",
            )
            session.add(row)
            await session.flush()
            return BatchView.model_validate(row)

    async def _administrator(self, session: AsyncSession, actor: int) -> Account:
        if actor not in self._admins:
            raise AccessDenied
        return await active_account(session, actor)

    async def admin_profile(self, actor: int) -> AccountView:
        """Verify current administrative authority without loading the user directory."""
        async with self._sessions.begin() as session:
            return AccountView.model_validate(await self._administrator(session, actor))

    async def users(self, actor: int, page: int = 0) -> list[AccountView]:
        """Preserve the bounded directory contract used by existing callers."""
        return (await self.user_directory(actor, page)).items

    async def user_directory(
        self,
        actor: int,
        page: int = 0,
        query: str = "",
        status: AccountFilter = AccountFilter.ALL,
    ) -> AccountPage:
        """Search metadata by literal name, internal ID or numeric Telegram ID."""
        if not 0 <= page <= 100000 or len(query) > 128:
            raise ValueError("Invalid directory query")
        query = query.strip()
        conditions: list[ColumnElement[bool]] = []
        if status != AccountFilter.ALL:
            conditions.append(Account.blocked.is_(status == AccountFilter.BLOCKED))
        if query:
            numeric = query.isascii() and query.isdigit()
            if numeric:
                telegram_id = int(query) if len(query) <= 19 else -1
                conditions.append(
                    Account.telegram_id == (telegram_id if telegram_id <= 2**63 - 1 else -1)
                )
            else:
                conditions.append(
                    or_(
                        Account.name.icontains(query, autoescape=True),
                        Account.id == query.lower(),
                    )
                )
        async with self._sessions.begin() as session:
            await self._administrator(session, actor)
            total = await session.scalar(
                select(func.count()).select_from(Account).where(*conditions)
            )
            rows = await session.scalars(
                select(Account)
                .where(*conditions)
                .order_by(Account.created_at, Account.id)
                .offset(page * 8)
                .limit(8)
            )
            return AccountPage(
                items=[AccountView.model_validate(row) for row in rows],
                total=total or 0,
                page=page,
            )

    async def change_status(
        self,
        actor: int,
        target_id: str,
        version: int,
        blocked: bool,
        reason: str,
    ) -> None:
        """Change status with optimistic concurrency and atomic audit."""
        if not reason.strip() or len(reason) > 200:
            raise ValueError("A reason of 1–200 characters is required")
        async with self._sessions.begin() as session:
            administrator = await self._administrator(session, actor)
            target = await session.scalar(
                select(Account).where(Account.id == target_id).with_for_update()
            )
            if target is None or target.telegram_id in self._admins:
                raise AccessDenied
            if target.version != version:
                raise Conflict
            if target.blocked == blocked:
                return
            target.blocked = blocked
            target.version += 1
            session.add(
                Audit(
                    actor_id=administrator.id,
                    target_id=target.id,
                    reason=reason.strip(),
                    blocked=blocked,
                )
            )

    async def admin_target(self, actor: int, target_id: str) -> AccountView:
        """Read target metadata without exposing inventory or media."""
        async with self._sessions.begin() as session:
            await self._administrator(session, actor)
            target = await session.get(Account, target_id)
            if target is None:
                raise AccessDenied
            return AccountView.model_validate(target)

    async def preview_purchase(
        self,
        actor: int,
        event_key: str,
        result: PhotoRecognition,
    ) -> PurchasePreview:
        """Persist a bounded preview without changing stock; newer input replaces older previews."""
        async with self._sessions.begin() as session:
            owner = await active_account(session, actor)
            key = f"{owner.id}:{event_key}"
            existing = await session.scalar(
                select(PurchaseDraft).where(PurchaseDraft.event_key == key)
            )
            if existing is not None:
                if existing.status != "pending":
                    raise Conflict
                return PurchasePreview(
                    id=UUID(existing.id), **load_contents(existing.payload).model_dump()
                )
            await session.execute(
                update(PurchaseDraft)
                .where(
                    PurchaseDraft.owner_id == owner.id,
                    PurchaseDraft.status == "pending",
                )
                .values(status="cancelled", payload={})
            )
            contents = PurchaseContents(
                result=result,
                estimates=[estimate_expiry(item, self._today()) for item in result.products],
            )
            row = PurchaseDraft(
                owner_id=owner.id,
                event_key=key,
                payload=contents.model_dump(mode="json"),
                expires_at=datetime.now(UTC) + timedelta(minutes=30),
            )
            session.add(row)
            await session.flush()
            return PurchasePreview(id=UUID(row.id), **contents.model_dump())

    async def decide_purchase(
        self, actor: int, draft_id: str, accept: bool, use_estimates: bool = True
    ) -> int:
        """Apply a private preview atomically once, including all its inventory rows."""
        async with self._sessions.begin() as session:
            owner = await active_account(session, actor)
            row = await session.scalar(
                select(PurchaseDraft)
                .where(
                    PurchaseDraft.id == draft_id,
                    PurchaseDraft.owner_id == owner.id,
                )
                .with_for_update()
            )
            if row is None:
                raise AccessDenied
            if row.status != "pending" or row.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC):
                raise Conflict
            if not accept:
                row.status = "cancelled"
                row.payload = {}
                return 0
            contents = load_contents(row.payload)
            result = contents.result
            if not result.products or any(item.needs_clarification for item in result.products):
                raise Conflict
            commands = [to_stock(item) for item in result.products]
            for index, command in enumerate(commands):
                estimate = (
                    contents.estimates[index]
                    if use_estimates and index < len(contents.estimates)
                    else None
                )
                session.add(
                    Batch(
                        owner_id=owner.id,
                        event_key=f"purchase:{row.id}:{index}",
                        name=command.name,
                        quantity=command.quantity,
                        unit=command.unit,
                        expiry=command.expiry or (estimate.expiry if estimate else None),
                        expiry_source=(
                            "confirmed"
                            if command.expiry
                            else "estimated"
                            if estimate
                            else "unknown"
                        ),
                        expiry_estimate=estimate.model_dump(mode="json") if estimate else None,
                    )
                )
            row.status = "saved"
            row.payload = {}
            return len(commands)

    async def stock_item(self, actor: int, identifier: str) -> BatchView:
        """Commit own expiry cleanup before rejecting a stale or foreign card."""
        async with self._sessions.begin() as session:
            owner = await active_account(session, actor)
            await purge_owner(session, owner.id, self._today())
            row = await session.scalar(
                select(Batch).where(Batch.id == identifier, Batch.owner_id == owner.id)
            )
            view = BatchView.model_validate(row) if row is not None else None
        if view is None:
            raise AccessDenied
        return view
