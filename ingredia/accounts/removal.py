"""Транзакционное удаление запасов с ограниченными по времени снимками версий."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ingredia.accounts.access import active_account
from ingredia.accounts.models import AccessDenied, Conflict
from ingredia.storage.models import Batch, RemovedStockEvent, StockRemovalDraft


class RemovalPlan(BaseModel):
    """Описать удаление для показа пользователю без передачи прав в callback.

    Attributes:
        id: Идентификатор серверного плана удаления.
        count: Количество партий, включённых в план.
        name: Название выбранной партии или None при очистке всего холодильника.
    """

    id: UUID
    count: int
    name: str | None


class StockRemovalService:
    """Выполнять удаление под общей блокировкой аккаунта владельца."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        """Сохранить фабрику транзакционных сессий хранилища.

        Args:
            sessions: Фабрика сессий для атомарной проверки владельца и удаления партий.
        """
        self._sessions = sessions

    async def delete_one(
        self,
        actor: int,
        batch_id: str,
        version: int | None = None,
    ) -> bool:
        """Удалить собственную партию с необязательной проверкой версии.

        Args:
            actor: Доверенный числовой Telegram ID пользователя, выполняющего действие.
            batch_id: Внутренний ID удаляемой партии.
            version: Ожидаемая версия партии; None отключает только проверку версии.

        Returns:
            True, если партия удалена; False, если доступная владельцу партия не найдена.

        Raises:
            AccessDenied: Аккаунт пользователя отсутствует или заблокирован.
            Conflict: Переданная версия отличается от текущей версии партии.
        """
        async with self._sessions.begin() as session:
            owner = await active_account(session, actor)
            row = await session.scalar(
                select(Batch)
                .where(
                    Batch.owner_id == owner.id,
                    Batch.id == batch_id,
                )
                .with_for_update()
            )
            if row is None:
                return False
            if version is not None and row.version != version:
                raise Conflict
            await self._delete(session, [row], owner.id)
            return True

    async def plan(self, actor: int, batch_id: str | None = None) -> RemovalPlan:
        """Сохранить снимок партий для подтверждения удаления на десять минут.

        Новый план отменяет прежние ожидающие планы этого владельца.

        Args:
            actor: Доверенный числовой Telegram ID владельца запасов.
            batch_id: ID одной партии или None для снимка всего холодильника.

        Returns:
            Идентификатор плана и сведения о его объёме для экрана подтверждения.

        Raises:
            AccessDenied: Аккаунт недоступен или в выбранной области нет собственных партий.
        """
        async with self._sessions.begin() as session:
            owner = await active_account(session, actor)
            query = select(Batch).where(Batch.owner_id == owner.id)
            if batch_id is not None:
                query = query.where(Batch.id == batch_id)
            rows = list(await session.scalars(query.order_by(Batch.id)))
            if not rows:
                raise AccessDenied
            await session.execute(
                update(StockRemovalDraft)
                .where(
                    StockRemovalDraft.owner_id == owner.id,
                    StockRemovalDraft.status == "pending",
                )
                .values(status="cancelled", payload=[])
            )
            row = StockRemovalDraft(
                owner_id=owner.id,
                mode="item" if batch_id is not None else "all",
                payload=[{"id": item.id, "version": item.version} for item in rows],
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
            session.add(row)
            await session.flush()
            return RemovalPlan(
                id=UUID(row.id),
                count=len(rows),
                name=rows[0].name if batch_id is not None else None,
            )

    async def decide(self, actor: int, identifier: str, accept: bool) -> int:
        """Подтвердить удаление актуального снимка или отменить его.

        Args:
            actor: Доверенный числовой Telegram ID пользователя, принимающего решение.
            identifier: ID сохранённого плана удаления.
            accept: True для удаления партий; False для отмены без изменения запасов.

        Returns:
            Количество удалённых партий или 0 при отмене.

        Raises:
            AccessDenied: Аккаунт недоступен или план не принадлежит пользователю.
            Conflict: План уже обработан, просрочен либо состав или версии партий изменились.
        """
        async with self._sessions.begin() as session:
            owner = await active_account(session, actor)
            draft = await session.scalar(
                select(StockRemovalDraft)
                .where(
                    StockRemovalDraft.id == identifier,
                    StockRemovalDraft.owner_id == owner.id,
                )
                .with_for_update()
            )
            if draft is None:
                raise AccessDenied
            if draft.status != "pending" or draft.expires_at.replace(tzinfo=UTC) <= datetime.now(
                UTC
            ):
                raise Conflict
            if not accept:
                draft.status, draft.payload = "cancelled", []
                return 0
            expected = {str(item["id"]): int(str(item["version"])) for item in draft.payload}
            query = select(Batch).where(Batch.owner_id == owner.id)
            if draft.mode == "item":
                query = query.where(Batch.id.in_(expected))
            rows = list(await session.scalars(query.with_for_update()))
            if not expected or {row.id: row.version for row in rows} != expected:
                raise Conflict
            await self._delete(session, rows, owner.id)
            draft.status, draft.payload = "done", []
            return len(rows)

    @staticmethod
    async def _delete(session: AsyncSession, rows: list[Batch], owner_id: str) -> None:
        """Удалить партии и атомарно сохранить ключи защиты от повторного добавления.

        Args:
            session: Сессия текущей транзакции с удерживаемой блокировкой владельца.
            rows: Проверенные партии для удаления; их ключи событий сохраняются перед удалением.
            owner_id: Внутренний ID владельца, ограничивающий SQL-запрос удаления.
        """
        for offset in range(0, len(rows), 500):
            portion = rows[offset : offset + 500]
            session.add_all(RemovedStockEvent(event_key=row.event_key) for row in portion)
            await session.flush()
            await session.execute(
                delete(Batch).where(
                    Batch.owner_id == owner_id,
                    Batch.id.in_([row.id for row in portion]),
                )
            )
