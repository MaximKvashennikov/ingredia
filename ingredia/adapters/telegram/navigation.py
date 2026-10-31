"""Private Telegram menu and manual inventory handlers."""

from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from pydantic import ValidationError

from ingredia.accounts.models import AccessDenied, BatchInput, Conflict, StockPage
from ingredia.accounts.service import AccountService
from ingredia.adapters.telegram.editing import replace_screen
from ingredia.adapters.telegram.menu import Menu, keyboard
from ingredia.adapters.telegram.views import stock_card, unit_label
from ingredia.clock import current_date


class Navigation:
    """Render account views without coupling the service to aiogram."""

    def __init__(self, service: AccountService) -> None:
        """Inject transactional application operations."""
        self.service = service

    async def menu(self, message: Message) -> None:
        """Register the verified private sender and show available navigation."""
        if message.from_user is None:
            return
        try:
            await self.service.register(message.from_user.id, message.from_user.full_name)
        except AccessDenied:
            await message.answer("Доступ к аккаунту заблокирован.")
            return
        await message.answer(
            "🌿 <b>ingredia</b>\nВаш виртуальный холодильник.\n\nС чего начнём?",
            parse_mode="HTML",
            reply_markup=keyboard(),
        )

    async def profile(self, message: Message) -> None:
        """Show the sender's account; never accept a user ID from message text."""
        if message.from_user is None:
            return
        account = await self.service.profile(message.from_user.id)
        await message.answer(
            f"👤 <b>Личный кабинет</b>\n\n{escape(account.name)}\n🟢 Аккаунт активен\n\nВаши продукты — в разделе «🧊 Мой холодильник».",
            parse_mode="HTML",
            reply_markup=keyboard(),
        )

    async def fridge(self, message: Message) -> None:
        """Show a compact product selector instead of a long stream of detailed cards."""
        if message.from_user is None:
            return
        argument = (message.text or "").partition(" ")[2]
        page = int(argument) - 1 if argument.isdigit() and len(argument) <= 6 else 0
        stock = await self.service.stock_page(message.from_user.id, max(0, page))
        await message.answer(
            self.fridge_text(stock),
            parse_mode="HTML",
            reply_markup=self.pages(stock),
        )

    @staticmethod
    def fridge_text(stock: StockPage) -> str:
        """Keep the list header short; details belong to the selected item."""
        if not stock.items:
            return "🧊 <b>Холодильник пуст</b>\n\nНажмите «🛒 Добавить покупки» и пришлите фото или список."
        return (
            f"🧊 <b>Мой холодильник</b> · {stock.total} поз.\n"
            f"Страница {stock.page + 1} из {(stock.total + 5) // 6}\n\n"
            "Выберите продукт — откроются количество и срок.\n"
            "≈ — дата по оценке."
        )

    @staticmethod
    def pages(stock: StockPage) -> InlineKeyboardMarkup:
        """Use six compact product buttons with exact navigation boundaries."""
        rows = []
        for item in stock.items:
            quantity = (
                f"{item.quantity.normalize():f} {unit_label(item.unit)}" if item.quantity else "?"
            )
            expiry = ""
            if item.expiry:
                prefix = "≈" if item.expiry_source == "estimated" else ""
                expiry = f" · {prefix}{item.expiry:%d.%m}"
            icon = "⚠️" if item.expiry and item.expiry < current_date() else "📦"
            label = f"{icon} {item.name[:28]} · {quantity}{expiry}"
            rows.append(
                [
                    InlineKeyboardButton(
                        text=label,
                        callback_data=f"stock:{item.id}:{stock.page}",
                    )
                ]
            )
        controls = []
        if stock.page > 0:
            controls.append(
                InlineKeyboardButton(text="← Назад", callback_data=f"fridge:{stock.page - 1}")
            )
        if stock.has_next:
            controls.append(
                InlineKeyboardButton(text="Далее →", callback_data=f"fridge:{stock.page + 1}")
            )
        controls.append(
            InlineKeyboardButton(text="🔄 Обновить", callback_data=f"fridge:{stock.page}")
        )
        rows.append(controls)
        rows.append([InlineKeyboardButton(text="🍳 Что приготовить", callback_data="recipes:new")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def fridge_page(self, callback: CallbackQuery, bot: Bot) -> None:
        """Edit the current inventory screen rather than sending another long list."""
        argument = (callback.data or "").partition(":")[2]
        if not argument.isdigit() or len(argument) > 6 or int(argument) > 100000:
            await callback.answer("Недоступная страница.")
            return
        try:
            stock = await self.service.stock_page(callback.from_user.id, int(argument))
        except AccessDenied:
            await callback.answer("Холодильник недоступен.", show_alert=True)
            return
        await callback.answer()
        await replace_screen(callback, bot, self.fridge_text(stock), self.pages(stock))

    async def stock_item(self, callback: CallbackQuery, bot: Bot) -> None:
        """Show one owner-bound batch and return to the same fridge page."""
        parts = (callback.data or "").split(":")
        if len(parts) != 3 or not parts[2].isdigit() or len(parts[2]) > 6:
            await callback.answer("Недоступная карточка.")
            return
        try:
            item = await self.service.stock_item(callback.from_user.id, parts[1])
        except AccessDenied:
            await callback.answer("Продукт недоступен.", show_alert=True)
            return
        await callback.answer()
        await replace_screen(
            callback,
            bot,
            stock_card(item),
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="← К холодильнику", callback_data=f"fridge:{parts[2]}"
                        )
                    ]
                ]
            ),
        )

    @staticmethod
    async def purchases(message: Message) -> None:
        """Offer a photo first and natural text as an equally available alternative."""
        await message.answer(
            "🛒 <b>Добавим покупки</b>\n\n"
            "📸 <b>Пришлите фото продуктов</b>\nРазложите покупки так, чтобы их было видно.\n\n"
            "✍️ <b>Или напишите своими словами</b>\n"
            "Например: «Купил два литра молока, шесть яиц и три яблока».\n\n"
            "Я покажу список — вы проверите его и подтвердите добавление.",
            parse_mode="HTML",
            reply_markup=keyboard(),
        )

    async def add(self, message: Message) -> None:
        """Validate explicit manual input and deduplicate Telegram redelivery."""
        if message.from_user is None:
            return
        fields = (message.text or "").partition(" ")[2].split("|")
        fields += [""] * (4 - len(fields))
        try:
            name, quantity, unit, expiry = (value.strip() for value in fields)
            data = BatchInput.model_validate(
                {
                    "name": name,
                    "quantity": quantity or None,
                    "unit": unit or None,
                    "expiry": expiry or None,
                }
            )
        except (ValidationError, ValueError):
            await message.answer(
                "Не удалось разобрать покупку. Формат: /add название | число | единица | YYYY-MM-DD"
            )
            return
        try:
            await self.service.add(message.from_user.id, f"user:{message.message_id}", data)
        except Conflict:
            await message.answer("Это добавление уже обрабатывалось; устаревшая партия удалена.")
            return
        await message.answer("Покупка сохранена в холодильник.")

    @staticmethod
    async def help(message: Message) -> None:
        """Explain safe photo processing and navigation."""
        await message.answer(
            "❓ <b>Как пользоваться ingredia</b>\n\n"
            "1. Откройте «🛒 Добавить покупки».\n"
            "2. Пришлите фото или напишите список.\n"
            "3. Проверьте результат и нажмите «✅ Добавить».\n\n"
            "Фото и текст обрабатываются внешней облачной моделью. "
            "Справочные сроки помечаю «по оценке». Рецепты — в «🍳 Что приготовить».\n\n/id — ваш Telegram ID.",
            parse_mode="HTML",
        )


def navigation_router(service: AccountService) -> Router:
    """Register menu commands before the photo trial's fallback handler."""
    view = Navigation(service)
    router = Router(name="navigation")
    router.callback_query.filter(F.message.chat.type == "private")
    router.callback_query.register(view.stock_item, F.data.startswith("stock:"))
    router.callback_query.register(view.fridge_page, F.data.startswith("fridge:"))
    router.message.filter(F.chat.type == "private", F.from_user)
    router.message.register(view.menu, Command("start", "menu"))
    router.message.register(view.menu, F.text.in_({Menu.HOME, "В меню"}))
    router.message.register(view.profile, F.text.in_({Menu.PROFILE, "Личный кабинет"}))
    router.message.register(view.fridge, Command("fridge"))
    router.message.register(view.fridge, F.text.in_({Menu.FRIDGE, "Мой холодильник"}))
    router.message.register(view.purchases, F.text.in_({Menu.PURCHASES, "Добавить покупки"}))
    router.message.register(view.add, Command("add"))
    router.message.register(view.help, F.text.in_({Menu.HELP, "Помощь"}))
    return router
