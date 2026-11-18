"""Меню, личный кабинет и навигация по холодильнику в личном чате Telegram."""

from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputRichMessage,
    Message,
)
from pydantic import ValidationError

from ingredia.accounts.models import AccessDenied, BatchInput, Conflict, StockPage
from ingredia.accounts.service import AccountService
from ingredia.adapters.telegram.editing import replace_screen
from ingredia.adapters.telegram.fridge_views import stock_content, stock_details
from ingredia.adapters.telegram.menu import Menu, keyboard


class Navigation:
    """Представлять личные данные через Telegram без привязки ядра к aiogram.

    Attributes:
        service: Прикладной сервис аккаунтов, запасов и подтверждённых покупок.
    """

    def __init__(self, service: AccountService) -> None:
        """Сохранить прикладной сервис для обработчиков навигации.

        Args:
            service: Сервис с транзакционными операциями и проверкой доступа к личным данным.
        """
        self.service = service

    async def menu(self, message: Message) -> None:
        """Зарегистрировать отправителя личного сообщения и показать главное меню.

        Args:
            message: Личное сообщение с доверенными данными отправителя из Telegram.
        """
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
        """Показать личный кабинет отправителя сообщения.

        Args:
            message: Личное сообщение, по отправителю которого определяется владелец аккаунта.

        Raises:
            AccessDenied: Аккаунт отправителя отсутствует или заблокирован.
        """
        if message.from_user is None:
            return
        account = await self.service.profile(message.from_user.id)
        await message.answer(
            f"👤 <b>Личный кабинет</b>\n\n{escape(account.name)}\n🟢 Аккаунт активен\n\nВаши продукты — в разделе «🧊 Мой холодильник».",
            parse_mode="HTML",
            reply_markup=keyboard(),
        )

    async def fridge(self, message: Message, bot: Bot) -> None:
        """Отправить компактную страницу холодильника с действиями над запасами.

        Args:
            message: Личное сообщение с необязательным номером страницы команды /fridge от единицы.
            bot: Клиент Telegram для отправки rich-сообщения.

        Raises:
            AccessDenied: Аккаунт отправителя отсутствует или заблокирован.
            ValueError: Номер страницы команды выходит за допустимый диапазон сервиса.
        """
        if message.from_user is None:
            return
        argument = (message.text or "").partition(" ")[2]
        page = int(argument) - 1 if argument.isdigit() and len(argument) <= 6 else 0
        stock = await self.service.stock_page(message.from_user.id, max(0, page))
        await bot.send_rich_message(
            message.chat.id,
            self.fridge_content(stock),
            reply_markup=self.pages(stock),
        )

    @staticmethod
    def fridge_content(stock: StockPage, banner: str = "") -> InputRichMessage:
        """Подготовить содержимое страницы холодильника.

        Args:
            stock: Текущая страница собственных запасов пользователя.
            banner: Необязательное уведомление перед заголовком холодильника.

        Returns:
            Rich-сообщение с компактной таблицей или описанием пустого состояния.
        """
        return stock_content(stock, banner)

    @staticmethod
    def pages(stock: StockPage) -> InlineKeyboardMarkup:
        """Сформировать нижние кнопки навигации и действий холодильника.

        Args:
            stock: Страница запасов с признаками доступности соседних страниц и продуктов.

        Returns:
            Inline-клавиатура с пагинацией, обновлением, подбором блюд и доступной очисткой.
        """
        rows = []
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
        if stock.items:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="🧹 Очистить холодильник", callback_data=f"clear:{stock.page}"
                    )
                ]
            )
        rows.append([InlineKeyboardButton(text="🍳 Что приготовить", callback_data="recipes:new")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def fridge_page(self, callback: CallbackQuery, bot: Bot) -> None:
        """Обновить страницу холодильника в исходном сообщении.

        Args:
            callback: Нажатие кнопки с номером страницы от нуля.
            bot: Клиент Telegram для редактирования текущего экрана.
        """
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
        await replace_screen(callback, bot, self.fridge_content(stock), self.pages(stock))

    async def stock_item(self, callback: CallbackQuery, bot: Bot) -> None:
        """Открыть полную карточку собственной партии и сохранить путь назад.

        Args:
            callback: Нажатие названия продукта с ID партии и номером страницы от нуля.
            bot: Клиент Telegram для замены списка полной карточкой.
        """
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
            stock_details(item, parts[2]),
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="← К холодильнику", callback_data=f"fridge:{parts[2]}"
                        )
                    ],
                ]
            ),
        )

    @staticmethod
    async def purchases(message: Message) -> None:
        """Показать способы добавления покупок с приоритетом фотографии.

        Args:
            message: Личное сообщение пользователя, которому отправляется инструкция.
        """
        await message.answer(
            "🛒 <b>Добавим покупки</b>\n\n"
            "🧾 <b>Фото чека из магазина</b>\nСнимите товарные строки чётко, без бликов.\n\n"
            "📸 <b>Или фото продуктов</b>\nРазложите покупки так, чтобы их было видно.\n\n"
            "✍️ <b>Или напишите своими словами</b>\n"
            "Например: «Купил два литра молока, шесть яиц и три яблока».\n\n"
            "Я покажу список — вы проверите его и подтвердите добавление.",
            parse_mode="HTML",
            reply_markup=keyboard(),
        )

    async def add(self, message: Message) -> None:
        """Добавить покупку из команды /add с проверкой повторной доставки.

        Args:
            message: Личное сообщение с названием, количеством, единицей и датой через разделитель |.

        Raises:
            AccessDenied: Аккаунт отправителя отсутствует или заблокирован.
        """
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
            await message.answer(
                "Это сообщение уже обработано. Удалённый продукт повторно не добавляется."
            )
            return
        await message.answer("Покупка сохранена в холодильник.")

    @staticmethod
    async def help(message: Message) -> None:
        """Показать справку о навигации и обработке покупок облачной моделью.

        Args:
            message: Личное сообщение пользователя, которому отправляется справка.
        """
        await message.answer(
            "❓ <b>Как пользоваться ingredia</b>\n\n"
            "1. Откройте «🛒 Добавить покупки».\n"
            "2. Пришлите фото чека, фото продуктов или напишите список.\n"
            "3. Проверьте результат и нажмите «✅ Добавить».\n\n"
            "Фото и текст обрабатываются внешней облачной моделью. "
            "Справочные сроки помечаю «по оценке». Рецепты — в «🍳 Что приготовить».\n\n/id — ваш Telegram ID.",
            parse_mode="HTML",
        )


def navigation_router(service: AccountService) -> Router:
    """Создать маршрутизатор меню и личных экранов перед общими обработчиками.

    Args:
        service: Прикладной сервис аккаунтов и холодильника с проверкой доступа.

    Returns:
        Маршрутизатор личных сообщений и callback для меню, карточек и страниц холодильника.
    """
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
