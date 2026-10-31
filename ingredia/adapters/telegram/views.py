"""Readable HTML cards shared by inventory and purchase presentations."""

from html import escape

from ingredia.accounts.expiry import ExpiryEstimate
from ingredia.accounts.models import BatchView
from ingredia.clock import current_date
from ingredia.recognition.models import ProductObservation


def unit_label(unit: str | None) -> str:
    """Translate a validated storage unit for human-readable messages."""
    labels = {"g": "г", "kg": "кг", "ml": "мл", "l": "л", "pcs": "шт."}
    return labels.get(unit or "", "")


def stock_card(item: BatchView) -> str:
    """Render one private batch with date provenance and estimate conditions."""
    quantity = (
        f"{item.quantity.normalize():f} {unit_label(item.unit)}" if item.quantity else "не указано"
    )
    expiry = item.expiry.strftime("%d.%m.%Y") if item.expiry else "не указан"
    provenance = " (по оценке)" if item.expiry_source == "estimated" else ""
    details = ""
    if item.expiry and item.expiry < current_date():
        details = "\n⚠️ Срок истёк; продукт исключён из подбора."
    if item.expiry_source in {"user", "confirmed"}:
        details += "\nИсточник: дата, указанная при добавлении."
    if item.expiry_estimate is not None:
        estimate = item.expiry_estimate
        details += (
            f"\n\nОриентир: {estimate.days} дн. от "
            f"{estimate.reference_date:%d.%m.%Y}.\n{escape(estimate.conditions)}."
            f'\nИсточник: <a href="{escape(estimate.source, quote=True)}">Nebraska Extension</a>.'
            "\nЭто плановая оценка, не гарантия свежести."
        )
    return f"<b>{escape(item.name)}</b>\n\n📦 {quantity}\n📅 Срок: {expiry}{provenance}{details}"


def candidate_card(
    item: ProductObservation,
    index: int,
    estimate: ExpiryEstimate | None = None,
) -> str:
    """Render unknown attributes and clarification questions explicitly."""
    amount = item.quantity_per_package
    quantity = "количество не указано"
    if amount is not None:
        count = f"{item.package_count} × " if item.package_count else ""
        quantity = f"{count}{amount.value:g} {unit_label(amount.unit)}"
    elif item.package_count is not None:
        quantity = f"{item.package_count} шт./уп."
    expiry = item.expiry_date.strftime("%d.%m.%Y") if item.expiry_date else "не указан"
    if estimate is not None:
        expiry = (
            f"{estimate.expiry:%d.%m.%Y} · по оценке ({estimate.days} дн.)"
            f"\n   {escape(estimate.conditions)}"
        )
    question = (
        f"\n   ❓ {escape(item.clarification_question or '')}" if item.needs_clarification else ""
    )
    return (
        f"{index}. <b>{escape(item.name or item.visual_description)}</b>\n"
        f"   📦 {quantity}\n   📅 Срок: {expiry}{question}"
    )
