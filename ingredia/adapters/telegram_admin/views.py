"""Short HTML views and inline controls for account administration."""

from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ingredia.accounts.models import AccountFilter, AccountPage, AccountView
from ingredia.adapters.telegram_admin.models import DirectoryContext, StatusSelection


def directory_text(result: AccountPage, context: DirectoryContext) -> str:
    """Explain the current filter and search without dumping UUIDs."""
    label = {
        AccountFilter.ALL: "Все пользователи",
        AccountFilter.ACTIVE: "Активные",
        AccountFilter.BLOCKED: "Заблокированные",
    }[context.status]
    query = f"\n🔎 Поиск: {escape(context.query)}" if context.query else ""
    if not result.items:
        return f"👥 <b>{label}</b>{query}\n\nНикого не найдено.\nИзмените поиск или фильтр."
    pages = max(1, (result.total + 7) // 8)
    return (
        f"👥 <b>{label}</b>{query}\n\nНайдено: {result.total}\n"
        f"Страница {result.page + 1} из {pages}\n\nВыберите пользователя:"
    )


def directory_keyboard(result: AccountPage, context: DirectoryContext) -> InlineKeyboardMarkup:
    """Render distinct users and retain an opaque actor-bound directory context."""
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'🔴' if user.blocked else '🟢'} {user.name[:35]} · {user.telegram_id}",
                callback_data=f"au:{context.token}:{user.id}",
            )
        ]
        for user in result.items
    ]
    pages = []
    if result.page:
        pages.append(
            InlineKeyboardButton(
                text="← Назад", callback_data=f"ap:{context.token}:{result.page - 1}"
            )
        )
    if result.has_next:
        pages.append(
            InlineKeyboardButton(
                text="Далее →", callback_data=f"ap:{context.token}:{result.page + 1}"
            )
        )
    if pages:
        rows.append(pages)
    rows.append(
        [
            InlineKeyboardButton(text="Все", callback_data=f"af:{context.token}:all"),
            InlineKeyboardButton(text="🟢 Активные", callback_data=f"af:{context.token}:active"),
            InlineKeyboardButton(text="🔴 Блок", callback_data=f"af:{context.token}:blocked"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="🔎 Поиск", callback_data="asearch"),
            InlineKeyboardButton(text="🏠 В меню", callback_data="ahome"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def account_card(account: AccountView, administrator: bool) -> str:
    """Show minimal metadata with no access to stock, favorites or media."""
    role = "Администратор" if administrator else "Пользователь"
    status = "🔴 Заблокирован" if account.blocked else "🟢 Активен"
    return (
        f"👤 <b>{escape(account.name)}</b>\n\n"
        f"Статус: {status}\nРоль: {role}\n"
        f"📅 Регистрация: {account.created_at.strftime('%d.%m.%Y')}\n"
        f"Telegram ID: <code>{account.telegram_id}</code>\n"
        f"ID аккаунта: <code>{account.id}</code>\n\n"
        "Личные продукты и сообщения здесь не отображаются."
    )


def card_keyboard(selection: StatusSelection | None) -> InlineKeyboardMarkup:
    """Expose a status action only for ordinary accounts and allow returning to results."""
    rows = []
    if selection is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔒 Заблокировать" if selection.blocked else "🔓 Разблокировать",
                    callback_data=f"act:{selection.token}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="⬅️ К списку", callback_data="alist")])
    rows.append([InlineKeyboardButton(text="🏠 В меню", callback_data="ahome")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
