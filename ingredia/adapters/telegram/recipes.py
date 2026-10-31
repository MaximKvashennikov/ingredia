"""Telegram recipe and favorite actions, independent of AI provider details."""

from hashlib import blake2b

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ingredia.accounts.models import AccessDenied
from ingredia.adapters.telegram.editing import replace_screen
from ingredia.adapters.telegram.menu import Menu
from ingredia.adapters.telegram.models import FailureReply
from ingredia.adapters.telegram.recipe_views import recipe_buttons, recipe_card
from ingredia.logging_config import get_logger
from ingredia.recipes.service import RecipeService
from ingredia.recognition.errors import RecognitionFailure

logger = get_logger(__name__)


class RecipeHandlers:
    """Present generated cards and persistent personal favorites with current ownership."""

    def __init__(self, service: RecipeService | None) -> None:
        """Inject an optional recipe service for legacy recognition-only runs."""
        self.service = service

    async def generate(self, actor: int, event_id: int, bot: Bot) -> None:
        """Generate on explicit request; never spend quota while merely listing stock."""
        if self.service is None:
            await bot.send_message(actor, "Подбор рецептов не подключён.")
            return
        await bot.send_message(actor, "🍳 Подбираю блюда по вашему холодильнику…")
        try:
            views = await self.service.generate(actor, event_id)
        except AccessDenied:
            await bot.send_message(actor, "Доступ к аккаунту заблокирован.")
            return
        except RecognitionFailure as error:
            logger.warning("Recipe generation failed: category=%s", error.code.value)
            await bot.send_message(actor, FailureReply.from_failure(error).render())
            return
        if not views:
            await bot.send_message(
                actor,
                "🧊 Пока нет продуктов для подбора.\n"
                "Добавьте покупки. Продукты с истёкшим сроком в подбор не входят.",
            )
            return
        logger.info("Recipe suggestions ready: count=%d", len(views))
        for view in views:
            await bot.send_message(
                actor,
                recipe_card(view),
                parse_mode="HTML",
                reply_markup=recipe_buttons(view),
            )

    async def message_generate(self, message: Message, bot: Bot) -> None:
        """Start suggestions from the main menu using a verified private sender."""
        if message.from_user:
            await self.generate(message.from_user.id, message.message_id, bot)

    async def callback_generate(self, callback: CallbackQuery, bot: Bot) -> None:
        """Acknowledge a button before a slow AI request and deduplicate its event identity."""
        await callback.answer()
        digest = blake2b(callback.id.encode(), digest_size=8).digest()
        await self.generate(callback.from_user.id, -int.from_bytes(digest, "big"), bot)

    async def card(self, callback: CallbackQuery, bot: Bot) -> None:
        """Open or change an own favorite; stale and foreign IDs reveal no content."""
        if self.service is None:
            await callback.answer("Раздел недоступен.")
            return
        action, _, identifier = (callback.data or "").partition(":")
        try:
            if action in {"save", "unsave"}:
                await self.service.favorite(callback.from_user.id, identifier, action == "save")
            view = await self.service.get(callback.from_user.id, identifier)
        except AccessDenied:
            await callback.answer("Рецепт недоступен. Откройте избранное заново.", show_alert=True)
            return
        await callback.answer(
            "Сохранено" if action == "save" else "Убрано" if action == "unsave" else None
        )
        await replace_screen(callback, bot, recipe_card(view), recipe_buttons(view))

    async def favorites_screen(self, actor: int, page: int) -> tuple[str, InlineKeyboardMarkup]:
        """Build a six-item favorites page without generating another recipe."""
        items = await self.service.favorites(actor, page) if self.service else []
        text = "⭐ <b>Избранные рецепты</b>\n\nВыберите блюдо."
        if not items:
            text = "⭐ <b>Избранное пока пусто</b>\n\nСохраните понравившееся блюдо из карточки рецепта."
        rows = [
            [
                InlineKeyboardButton(
                    text="🍽 " + title[:55],
                    callback_data=f"recipe:{identifier}",
                )
            ]
            for identifier, title in items[:6]
        ]
        controls = []
        if page:
            controls.append(
                InlineKeyboardButton(text="← Назад", callback_data=f"favorites:{page - 1}")
            )
        if len(items) > 6:
            controls.append(
                InlineKeyboardButton(text="Далее →", callback_data=f"favorites:{page + 1}")
            )
        if controls:
            rows.append(controls)
        rows.append([InlineKeyboardButton(text="🍳 Подобрать блюда", callback_data="recipes:new")])
        return text, InlineKeyboardMarkup(inline_keyboard=rows)

    async def message_favorites(self, message: Message) -> None:
        """List own favorites from the reply menu."""
        if message.from_user is None:
            return
        text, markup = await self.favorites_screen(message.from_user.id, 0)
        await message.answer(text, parse_mode="HTML", reply_markup=markup)

    async def callback_favorites(self, callback: CallbackQuery, bot: Bot) -> None:
        """Navigate the originating favorites screen without accumulating lists."""
        value = (callback.data or "").partition(":")[2]
        if not value.isdigit() or len(value) > 6 or int(value) > 100000:
            await callback.answer("Недоступная страница.")
            return
        try:
            text, markup = await self.favorites_screen(callback.from_user.id, int(value))
        except AccessDenied:
            await callback.answer("Избранное недоступно.", show_alert=True)
            return
        await callback.answer()
        await replace_screen(callback, bot, text, markup)


def recipes_router(service: RecipeService | None) -> Router:
    """Register private menu actions and owner-checked recipe callback routes."""
    handlers = RecipeHandlers(service)
    router = Router(name="recipes")
    router.message.filter(F.chat.type == "private", F.from_user)
    router.callback_query.filter(F.message.chat.type == "private")
    router.message.register(
        handlers.message_generate, F.text.in_({Menu.RECIPES, "Что приготовить"})
    )
    router.message.register(handlers.message_favorites, F.text.in_({Menu.FAVORITES, "Избранное"}))
    router.callback_query.register(handlers.callback_generate, F.data == "recipes:new")
    router.callback_query.register(handlers.callback_favorites, F.data.startswith("favorites:"))
    router.callback_query.register(
        handlers.card,
        F.data.startswith("recipe:") | F.data.startswith("save:") | F.data.startswith("unsave:"),
    )
    return router
