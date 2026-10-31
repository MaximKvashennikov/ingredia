"""Button-driven administrative navigation with short, explicit text steps."""

from time import monotonic

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ingredia.accounts.models import AccountFilter
from ingredia.accounts.service import AccountService
from ingredia.adapters.telegram_admin.handlers import AdminHandlers
from ingredia.adapters.telegram_admin.menu import admin_keyboard
from ingredia.adapters.telegram_admin.models import AdminFlow, DirectoryContext, StatusSelection
from ingredia.adapters.telegram_admin.views import (
    account_card,
    card_keyboard,
    directory_keyboard,
    directory_text,
)


class AdminNavigation:
    """Keep list navigation and text input out of the status mutation handlers."""

    def __init__(
        self,
        service: AccountService,
        actions: AdminHandlers,
        allowed: frozenset[int],
    ) -> None:
        """Inject application operations and the shared confirmation flow."""
        self.service = service
        self.actions = actions
        self.allowed = allowed

    @staticmethod
    async def context(state: FSMContext) -> DirectoryContext:
        """Restore typed navigation data scoped to this bot, chat and actor."""
        data = await state.get_data()
        return DirectoryContext.model_validate(data.get("navigation", {}))

    @staticmethod
    async def save(state: FSMContext, context: DirectoryContext) -> None:
        """Keep only validated directory metadata in the short-lived FSM store."""
        await state.update_data(navigation=context.model_dump(mode="json"))

    async def reset_step(self, state: FSMContext, actor: int) -> DirectoryContext:
        """Cancel unfinished input and confirmation while retaining search context."""
        context = await self.context(state)
        context.selection = None
        self.actions.pending.pop(actor, None)
        await state.set_state(None)
        await self.save(state, context)
        return context

    async def home(self, message: Message, state: FSMContext) -> None:
        """Show a persistent administrative keyboard instead of command instructions."""
        if message.from_user is None:
            return
        self.actions.pending.pop(message.from_user.id, None)
        await state.clear()
        await message.answer(
            "🛠 <b>ingredia · управление</b>\n\n"
            "👥 Просматривайте пользователей\n🔎 Находите аккаунты\n"
            "🔒 Управляйте доступом из карточки\n\nВыберите раздел в меню ↓",
            parse_mode="HTML",
            reply_markup=admin_keyboard(),
        )

    async def users(self, message: Message, state: FSMContext, bot: Bot) -> None:
        """Open all users with button pagination; retain the optional legacy command."""
        if message.from_user is None:
            return
        await self.reset_step(state, message.from_user.id)
        argument = (message.text or "").partition(" ")[2]
        page = (
            int(argument) - 1
            if argument.isascii() and argument.isdigit() and len(argument) <= 6
            else 0
        )
        context = DirectoryContext(page=max(0, page))
        await message.answer("👥 Открываю пользователей…", reply_markup=admin_keyboard())
        await self.show_directory(bot, message.from_user.id, state, context)

    async def blocked(self, message: Message, state: FSMContext, bot: Bot) -> None:
        """Open the blocked filter directly from the main menu."""
        if message.from_user is None:
            return
        await self.reset_step(state, message.from_user.id)
        await self.show_directory(
            bot,
            message.from_user.id,
            state,
            DirectoryContext(status=AccountFilter.BLOCKED),
        )

    async def search(self, message: Message, state: FSMContext) -> None:
        """Ask for a name or ID without a search command syntax."""
        if message.from_user is None:
            return
        await self.reset_step(state, message.from_user.id)
        await state.set_state(AdminFlow.search)
        await message.answer(
            "🔎 <b>Найти пользователя</b>\n\nНапишите имя, Telegram ID или ID аккаунта.\n"
            "Чтобы выйти, нажмите «⬅️ Назад» или «🏠 Главное меню».",
            parse_mode="HTML",
            reply_markup=admin_keyboard(),
        )

    async def search_query(self, message: Message, state: FSMContext, bot: Bot) -> None:
        """Apply a bounded literal query while preserving the chosen status filter."""
        if message.from_user is None:
            return
        query = (message.text or "").strip()
        if not query or len(query) > 128:
            await message.answer("Напишите имя или ID длиной до 128 символов.")
            return
        old = await self.context(state)
        await state.set_state(None)
        await self.show_directory(
            bot,
            message.from_user.id,
            state,
            DirectoryContext(query=query, status=old.status),
        )

    async def show_directory(
        self,
        bot: Bot,
        actor: int,
        state: FSMContext,
        context: DirectoryContext,
    ) -> None:
        """Fetch an authorized page and render matching navigation buttons."""
        result = await self.service.user_directory(
            actor, context.page, context.query, context.status
        )
        last_page = max(0, (result.total - 1) // 8)
        if context.page > last_page:
            context.page = last_page
            result = await self.service.user_directory(
                actor, context.page, context.query, context.status
            )
        context.selection = None
        await self.save(state, context)
        await bot.send_message(
            actor,
            directory_text(result, context),
            parse_mode="HTML",
            reply_markup=directory_keyboard(result, context),
        )

    async def directory_action(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        bot: Bot,
    ) -> None:
        """Reject stale or actor-mismatched directory controls before querying a target."""
        context = await self.context(state)
        parts = (callback.data or "").split(":", 2)
        if len(parts) != 3 or parts[1] != context.token:
            await callback.answer(
                "Этот список устарел. Откройте «👥 Пользователи».", show_alert=True
            )
            return
        action, _, argument = parts
        if action == "au":
            await self.show_card(bot, callback.from_user.id, state, context, argument)
            await callback.answer()
            return
        if action == "ap":
            if (
                not argument.isascii()
                or not argument.isdigit()
                or len(argument) > 6
                or int(argument) > 100000
            ):
                await callback.answer("Недоступная страница.")
                return
            context.page = int(argument)
        if action == "af":
            try:
                context = DirectoryContext(query=context.query, status=AccountFilter(argument))
            except ValueError:
                await callback.answer("Недоступный фильтр.")
                return
        await self.reset_step(state, callback.from_user.id)
        await callback.answer()
        await self.show_directory(bot, callback.from_user.id, state, context)

    async def show_card(
        self,
        bot: Bot,
        actor: int,
        state: FSMContext,
        context: DirectoryContext,
        target: str,
    ) -> None:
        """Build a fresh status selection only for a non-administrative account."""
        account = await self.service.admin_target(actor, target)
        administrator = account.telegram_id in self.allowed
        context.selection = None
        if not administrator:
            context.selection = StatusSelection(
                target=account.id,
                version=account.version,
                blocked=not account.blocked,
                expires=monotonic() + 300,
            )
        await state.set_state(None)
        self.actions.pending.pop(actor, None)
        await self.save(state, context)
        await bot.send_message(
            actor,
            account_card(account, administrator),
            parse_mode="HTML",
            reply_markup=card_keyboard(context.selection),
        )

    async def request_status(self, callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        """Ask for a reason after an actor-bound status button is chosen."""
        context = await self.context(state)
        selection = context.selection
        token = (callback.data or "").partition(":")[2]
        if selection is None or token != selection.token or selection.expires <= monotonic():
            await callback.answer(
                "Карточка устарела. Откройте пользователя заново.", show_alert=True
            )
            return
        current = await self.service.admin_target(callback.from_user.id, selection.target)
        if current.version != selection.version:
            await callback.answer("Статус уже изменился. Обновите карточку.", show_alert=True)
            return
        await state.set_state(AdminFlow.reason)
        await callback.answer()
        action = "блокировки" if selection.blocked else "разблокировки"
        await bot.send_message(
            callback.from_user.id,
            f"✍️ Напишите причину {action} одним сообщением (до 200 символов).\n\n"
            "Затем я попрошу подтвердить действие.\n«⬅️ Назад» — отменить ввод причины.",
            reply_markup=admin_keyboard(),
        )

    async def reason(self, message: Message, state: FSMContext) -> None:
        """Validate a reason and send the shared versioned confirmation."""
        if message.from_user is None:
            return
        context = await self.context(state)
        selection = context.selection
        if selection is None or selection.expires <= monotonic():
            await self.reset_step(state, message.from_user.id)
            await message.answer(
                "Карточка устарела. Выберите пользователя заново.", reply_markup=admin_keyboard()
            )
            return
        reason = (message.text or "").strip()
        if not reason or len(reason) > 200:
            await message.answer("Укажите причину от 1 до 200 символов. Или нажмите «⬅️ Назад».")
            return
        current = await self.service.admin_target(message.from_user.id, selection.target)
        if current.version != selection.version:
            await self.reset_step(state, message.from_user.id)
            await message.answer("Статус уже изменился. Откройте свежую карточку.")
            return
        await self.actions.ask_confirmation(message, current, selection.blocked, reason)
        context.selection = None
        await self.save(state, context)
        await state.set_state(None)

    async def back(self, message: Message, state: FSMContext, bot: Bot) -> None:
        """Leave a text step and return to its account or filtered list."""
        if message.from_user is None:
            return
        context = await self.context(state)
        selection = context.selection
        current_state = await state.get_state()
        await self.reset_step(state, message.from_user.id)
        if current_state == AdminFlow.reason.state and selection is not None:
            await self.show_card(bot, message.from_user.id, state, context, selection.target)
            return
        await self.show_directory(bot, message.from_user.id, state, context)

    async def list_back(self, callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        """Return to the previous search result without losing its filter or page."""
        context = await self.reset_step(state, callback.from_user.id)
        await callback.answer()
        await self.show_directory(bot, callback.from_user.id, state, context)

    async def home_callback(self, callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        """Clear unfinished actions and restore the main reply keyboard."""
        self.actions.pending.pop(callback.from_user.id, None)
        await state.clear()
        await callback.answer()
        await bot.send_message(
            callback.from_user.id,
            "🛠 <b>Главное меню</b>\n\nВыберите раздел ↓",
            parse_mode="HTML",
            reply_markup=admin_keyboard(),
        )

    async def search_callback(self, callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        """Start search from an inline control without typing a command."""
        await self.reset_step(state, callback.from_user.id)
        await state.set_state(AdminFlow.search)
        await callback.answer()
        await bot.send_message(
            callback.from_user.id,
            "🔎 Напишите имя, Telegram ID или ID аккаунта.",
            reply_markup=admin_keyboard(),
        )

    async def help(self, message: Message, state: FSMContext) -> None:
        """Explain the button flow instead of presenting a wall of commands."""
        if message.from_user is None:
            return
        await self.reset_step(state, message.from_user.id)
        await message.answer(
            "ℹ️ <b>Как управлять пользователями</b>\n\n"
            "1. Откройте «👥 Пользователи» или «🔎 Найти пользователя».\n"
            "2. Нажмите на нужный аккаунт.\n"
            "3. Выберите блокировку или разблокировку.\n"
            "4. Напишите причину и подтвердите действие.\n\n"
            "«⬅️ Назад» возвращает к списку. Данные холодильника здесь не видны.",
            parse_mode="HTML",
            reply_markup=admin_keyboard(),
        )

    async def command_status(self, message: Message, state: FSMContext) -> None:
        """Keep legacy commands working without carrying a stale text step forward."""
        if message.from_user is None:
            return
        await self.reset_step(state, message.from_user.id)
        await self.actions.prepare(message)

    @staticmethod
    async def unsupported(message: Message) -> None:
        """Explain the available navigation when an input has no administrative action."""
        await message.answer(
            "Выберите раздел в меню ↓\nДля поиска и причины действия пришлите обычный текст.",
            reply_markup=admin_keyboard(),
        )
