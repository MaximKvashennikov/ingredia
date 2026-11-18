"""Удаление отдельных продуктов и подтверждаемая очистка холодильника в Telegram."""

from uuid import UUID

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from ingredia.accounts.models import AccessDenied, Conflict
from ingredia.accounts.service import AccountService
from ingredia.adapters.telegram.editing import replace_screen
from ingredia.adapters.telegram.navigation import Navigation


class RemovalHandlers:
    """Обрабатывать удаление продуктов с серверной проверкой владельца.

    Attributes:
        service: Прикладной сервис доступа к аккаунтам, запасам и операциям удаления.
    """

    def __init__(self, service: AccountService) -> None:
        """Сохранить прикладной сервис операций с запасами.

        Args:
            service: Сервис с проверкой активности аккаунта и владения партиями.
        """
        self.service = service

    async def remove(self, callback: CallbackQuery, bot: Bot) -> None:
        """Удалить одну партию сразу и обновить текущую страницу холодильника.

        Args:
            callback: Нажатие кнопки с ID партии, страницей и необязательной ожидаемой версией.
            bot: Клиент Telegram для обновления исходного экрана.
        """
        parts = (callback.data or "").split(":")
        try:
            if len(parts) not in {3, 4} or parts[0] != "del":
                raise ValueError
            identifier, page = str(UUID(parts[1])), self._page(parts[2])
            version = None
            if len(parts) == 4:
                raw_version = parts[3]
                if not raw_version.isascii() or not raw_version.isdigit() or len(raw_version) > 10:
                    raise ValueError
                version = int(raw_version)
                if not 1 <= version <= 2147483647:
                    raise ValueError
            removed = await self.service.removals.delete_one(
                callback.from_user.id,
                identifier,
                version,
            )
        except (ValueError, AccessDenied):
            await callback.answer("Продукт недоступен.")
            return
        except Conflict:
            await callback.answer("Продукт изменился. Обновите холодильник.", show_alert=True)
            return
        await callback.answer("Удалено" if removed else "Продукт уже удалён или недоступен")
        stock = await self.service.stock_page(callback.from_user.id, page)
        await replace_screen(
            callback, bot, Navigation.fridge_content(stock), Navigation.pages(stock)
        )

    async def ask(self, callback: CallbackQuery, bot: Bot) -> None:
        """Показать подтверждение очистки всех продуктов владельца.

        Args:
            callback: Нажатие кнопки очистки с номером текущей страницы.
            bot: Клиент Telegram для замены списка экраном подтверждения.
        """
        parts = (callback.data or "").split(":")
        try:
            if len(parts) != 2 or parts[0] != "clear":
                raise ValueError
            page = self._page(parts[1])
            plan = await self.service.removals.plan(callback.from_user.id)
        except (ValueError, AccessDenied):
            await callback.answer("Холодильник уже пуст или недоступен.", show_alert=True)
            return
        text = (
            "🧹 <b>Очистить холодильник?</b>\n\n"
            f"Из холодильника будут удалены все продукты ({plan.count} поз.).\n"
            "Избранные рецепты сохранятся.\n\nОтменить удаление будет нельзя."
        )
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🧹 Да, очистить всё", callback_data=f"erase:{plan.id}:{page}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Оставить продукты", callback_data=f"keep:{plan.id}:{page}"
                    )
                ],
            ]
        )
        await callback.answer()
        await replace_screen(callback, bot, text, markup)

    async def decide(self, callback: CallbackQuery, bot: Bot) -> None:
        """Применить подтверждение или отмену очистки и вернуть актуальный список.

        Args:
            callback: Нажатие кнопки подтверждения или отмены с ID плана и номером страницы.
            bot: Клиент Telegram для обновления сообщения после обработки решения.
        """
        parts = (callback.data or "").split(":")
        try:
            if len(parts) != 3 or parts[0] not in {"erase", "keep"}:
                raise ValueError
            identifier, page = str(UUID(parts[1])), self._page(parts[2])
            count = await self.service.removals.decide(
                callback.from_user.id,
                identifier,
                parts[0] == "erase",
            )
        except (ValueError, AccessDenied):
            await callback.answer("Действие недоступно.", show_alert=True)
            return
        except Conflict:
            await callback.answer(
                "Список изменился или действие устарело. Откройте холодильник заново.",
                show_alert=True,
            )
            return
        await callback.answer("Удалено" if count else "Продукты оставлены")
        stock = await self.service.stock_page(callback.from_user.id, page)
        banner = f"✅ Удалено позиций: {count}.\n\n" if count else "Продукты оставлены.\n\n"
        await replace_screen(
            callback, bot, Navigation.fridge_content(stock, banner), Navigation.pages(stock)
        )

    @staticmethod
    def _page(value: str) -> int:
        """Проверить и преобразовать номер страницы из callback.

        Args:
            value: Номер страницы от нуля в виде строки из ASCII-цифр.

        Returns:
            Целое число от 0 до 100000 включительно.

        Raises:
            ValueError: Формат, длина или значение номера страницы недопустимы.
        """
        if not value.isascii() or not value.isdigit() or len(value) > 6 or int(value) > 100000:
            raise ValueError
        return int(value)


def removal_router(service: AccountService) -> Router:
    """Создать маршрутизатор удаления для личных сообщений.

    Args:
        service: Прикладной сервис, повторно проверяющий активность аккаунта и владельца данных.

    Returns:
        Маршрутизатор кнопок удаления, подтверждения и отмены очистки.
    """
    handlers = RemovalHandlers(service)
    router = Router(name="stock-removal")
    router.callback_query.filter(F.message.chat.type == "private")
    router.callback_query.register(handlers.remove, F.data.startswith("del:"))
    router.callback_query.register(handlers.ask, F.data.startswith("clear:"))
    router.callback_query.register(
        handlers.decide, F.data.startswith("erase:") | F.data.startswith("keep:")
    )
    return router
