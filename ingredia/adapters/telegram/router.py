"""Declare Telegram routing and private-chat filters in one place."""

from aiogram import Dispatcher, F, Router
from aiogram.filters import Command

from ingredia.accounts.service import AccountService
from ingredia.adapters.telegram.access import AccountAccess
from ingredia.adapters.telegram.handlers import PhotoHandlers
from ingredia.adapters.telegram.navigation import navigation_router
from ingredia.adapters.telegram.purchases import PurchaseHandlers
from ingredia.adapters.telegram.recipes import recipes_router
from ingredia.recipes.service import RecipeService
from ingredia.recognition.service import PhotoTrial


def create_dispatcher(
    trial: PhotoTrial,
    service: AccountService | None = None,
    recipes: RecipeService | None = None,
) -> Dispatcher:
    """Wire handler methods without nested functions or shared mutable module state."""
    handlers = PhotoHandlers(trial, service)
    router = Router(name="photo-trial")
    router.message.filter(F.chat.type == "private", F.from_user)
    router.message.register(handlers.identify, Command("start", "id"))
    router.message.register(handlers.recognize, F.photo)
    router.message.register(handlers.unsupported)
    router.errors.register(handlers.unexpected)
    dispatcher = Dispatcher()
    dispatcher.errors.register(handlers.unexpected)
    if service is not None:
        dispatcher.message.outer_middleware(AccountAccess(service))
        dispatcher.include_router(navigation_router(service))
        dispatcher.include_router(recipes_router(recipes))
        purchases = PurchaseHandlers(trial, service)
        purchase_router = Router(name="purchases")
        purchase_router.message.filter(F.chat.type == "private", F.from_user)
        purchase_router.callback_query.filter(F.message.chat.type == "private")
        purchase_router.message.register(
            purchases.photo, F.photo | F.document.mime_type.in_({"image/jpeg", "image/png"})
        )
        purchase_router.message.register(purchases.text, F.text & ~F.text.startswith("/"))
        purchase_router.callback_query.register(
            purchases.decide, F.data.startswith("buy:") | F.data.startswith("plain:")
        )
        purchase_router.callback_query.register(purchases.decide, F.data.startswith("drop:"))
        dispatcher.include_router(purchase_router)
    dispatcher.include_router(router)
    return dispatcher
