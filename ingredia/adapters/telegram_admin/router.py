"""Private, authorized routes for the administrative button interface."""

from aiogram import Dispatcher, F, Router
from aiogram.filters import Command

from ingredia.accounts.service import AccountService
from ingredia.adapters.telegram_admin.access import AdminAccess
from ingredia.adapters.telegram_admin.handlers import AdminHandlers
from ingredia.adapters.telegram_admin.menu import AdminMenu
from ingredia.adapters.telegram_admin.models import AdminFlow
from ingredia.adapters.telegram_admin.navigation import AdminNavigation


def create_admin_dispatcher(service: AccountService, allowed: frozenset[int]) -> Dispatcher:
    """Keep menu, text steps and administrative callbacks behind one access policy."""
    actions = AdminHandlers(service, allowed)
    view = AdminNavigation(service, actions, allowed)
    router = Router(name="administration")
    router.message.filter(F.chat.type == "private", F.from_user)
    router.callback_query.filter(F.message.chat.type == "private")
    router.message.register(view.home, Command("start", "menu"))
    router.message.register(view.users, Command("users"))
    router.message.register(view.command_status, Command("block", "unblock"))
    router.message.register(view.home, F.text == AdminMenu.HOME)
    router.message.register(view.users, F.text == AdminMenu.USERS)
    router.message.register(view.search, F.text == AdminMenu.SEARCH)
    router.message.register(view.blocked, F.text == AdminMenu.BLOCKED)
    router.message.register(view.help, F.text == AdminMenu.HELP)
    router.message.register(view.back, F.text == AdminMenu.BACK)
    router.message.register(view.search_query, AdminFlow.search, F.text & ~F.text.startswith("/"))
    router.message.register(view.reason, AdminFlow.reason, F.text & ~F.text.startswith("/"))
    router.message.register(view.unsupported)
    router.callback_query.register(view.home_callback, F.data == "ahome")
    router.callback_query.register(view.list_back, F.data == "alist")
    router.callback_query.register(view.search_callback, F.data == "asearch")
    router.callback_query.register(view.directory_action, F.data.startswith("au:"))
    router.callback_query.register(view.directory_action, F.data.startswith("ap:"))
    router.callback_query.register(view.directory_action, F.data.startswith("af:"))
    router.callback_query.register(view.request_status, F.data.startswith("act:"))
    router.callback_query.register(actions.confirm, F.data.startswith("status:"))
    router.callback_query.register(actions.confirm, F.data.startswith("cancel:"))
    dispatcher = Dispatcher()
    access = AdminAccess(service, allowed)
    dispatcher.message.outer_middleware(access)
    dispatcher.callback_query.outer_middleware(access)
    dispatcher.errors.register(actions.unexpected)
    dispatcher.include_router(router)
    return dispatcher
