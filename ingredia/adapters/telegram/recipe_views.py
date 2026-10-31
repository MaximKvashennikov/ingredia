"""Compact recipe cards with honest AI attribution and ingredient availability."""

from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ingredia.adapters.telegram.views import unit_label
from ingredia.recipes.models import Availability, RecipeView


def recipe_card(view: RecipeView) -> str:
    """Group ingredients by computed status and show a bounded sequence of steps."""
    recipe = view.snapshot.proposal
    lines = [
        f"🍳 <b>{escape(recipe.title)}</b>",
        f"👥 Порций: {recipe.servings} · ⏱ {recipe.minutes} мин.",
        f"<i>{escape(view.snapshot.source)}</i>",
    ]
    headings = {
        Availability.AVAILABLE: "✅ Есть по учёту",
        Availability.CHECK: "❓ Проверьте количество",
        Availability.MISSING: "🛒 Нужно дополнить",
    }
    for status, heading in headings.items():
        items = [item for item in view.ingredients if item.status == status]
        if not items:
            continue
        lines.extend(["", f"<b>{heading}</b>"])
        for item in items:
            ingredient = item.ingredient
            lines.append(
                f"• {escape(ingredient.name)} — {ingredient.quantity:g} "
                f"{unit_label(ingredient.unit)}"
            )
            if item.note != "Количество есть":
                lines.append(f"  <i>{escape(item.note)}</i>")
    lines.extend(["", "<b>Как приготовить</b>"])
    lines.extend(f"{i}. {escape(step)}" for i, step in enumerate(recipe.steps, 1))
    dates = [item.confirmed_expiry for item in view.ingredients if item.confirmed_expiry]
    if dates:
        lines.extend(["", f"📅 Ближайший подтверждённый срок: {min(dates):%d.%m.%Y}."])
    lines.extend(["", "Рецепт предложен AI. Проверьте продукты; запасы не списываются."])
    return "\n".join(lines)


def recipe_buttons(view: RecipeView) -> InlineKeyboardMarkup:
    """Use explicit desired favorite state so repeated callbacks remain idempotent."""
    action = "unsave" if view.favorite else "save"
    label = "⭐ В избранном · убрать" if view.favorite else "🤍 Сохранить рецепт"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"{action}:{view.id}")],
            [InlineKeyboardButton(text="⭐ Моё избранное", callback_data="favorites:0")],
            [InlineKeyboardButton(text="🧊 К холодильнику", callback_data="fridge:0")],
        ]
    )
