"""Читаемые HTML-карточки запасов и предварительного списка покупок."""

from html import escape

from ingredia.accounts.expiry import ExpiryEstimate
from ingredia.accounts.models import BatchView
from ingredia.clock import current_date
from ingredia.recognition.models import ProductObservation


def unit_label(unit: str | None) -> str:
    """Перевести код единицы измерения в русскую подпись.

    Args:
        unit: Код единицы хранения или None, если единица не указана.

    Returns:
        Короткая русская подпись либо пустая строка для отсутствующего или неизвестного кода.
    """
    labels = {"g": "г", "kg": "кг", "ml": "мл", "l": "л", "pcs": "шт."}
    return labels.get(unit or "", "")


def stock_expiry_text(item: BatchView, full_date: bool = False) -> str:
    """Описать срок словами без служебных значков и искусственных дат проверки.

    Args:
        item: Партия с датой и источником срока.
        full_date: Добавить год в дату для полной карточки продукта.

    Returns:
        Примерная или подтверждённая дата либо сообщение об отсутствии надёжной оценки.
    """
    if item.expiry is None or item.expiry_source == "review":
        return "Срок не рассчитан"
    formatted = item.expiry.strftime("%d.%m.%Y" if full_date else "%d.%m")
    label = "Примерно до" if item.expiry_source == "estimated" else "Годен до"
    return f"{label} {formatted}"


def stock_card(item: BatchView) -> str:
    """Сформировать полную карточку партии с происхождением срока.

    Args:
        item: Партия продукта с количеством, сроком и необязательной справочной оценкой.

    Returns:
        HTML-текст с экранированным названием, количеством, датой и условиями оценки.
    """
    quantity = (
        f"{item.quantity.normalize():f} {unit_label(item.unit)}" if item.quantity else "не указано"
    )
    details = ""
    if item.expiry and item.expiry_source != "review" and item.expiry < current_date():
        details = "\n⚠️ Срок истёк; продукт исключён из подбора."
    if item.expiry_source in {"user", "confirmed"}:
        details += "\nИсточник: дата, указанная при добавлении."
    if item.expiry_estimate is not None and item.expiry_source != "review":
        estimate = item.expiry_estimate
        details += (
            f"\n\nОриентир: {estimate.days} дн. от "
            f"{estimate.reference_date:%d.%m.%Y}.\n{escape(estimate.conditions)}."
            + (
                f'\nИсточник: <a href="{escape(estimate.source, quote=True)}">Nebraska Extension</a>.'
                if estimate.source.startswith("https://food.unl.edu/")
                else "\nИсточник: временный ориентир приложения."
            )
            + "\nЭто плановая оценка, не гарантия свежести."
        )
    return (
        f"<b>{escape(item.name)}</b>\n\n📦 {quantity}"
        f"\n📅 {stock_expiry_text(item, full_date=True)}{details}"
    )


def candidate_card(
    item: ProductObservation,
    index: int,
    estimate: ExpiryEstimate | None = None,
) -> str:
    """Сформировать карточку распознанного продукта до подтверждения покупки.

    Args:
        item: Наблюдение модели с атрибутами продукта и возможным вопросом для уточнения.
        index: Номер позиции для отображения в предварительном списке.
        estimate: Необязательная справочная оценка хранения; прежние даты проверки не показываются.

    Returns:
        HTML-карточка с количеством, сроком и явным обозначением неизвестных атрибутов.
    """
    amount = item.quantity_per_package
    quantity = "количество не указано"
    if amount is not None:
        count = f"{item.package_count} × " if item.package_count else ""
        quantity = f"{count}{amount.value:g} {unit_label(amount.unit)}"
    elif item.package_count is not None:
        quantity = f"{item.package_count} шт./уп."
    expiry = f"Годен до {item.expiry_date:%d.%m.%Y}" if item.expiry_date else "Срок не рассчитан"
    if estimate is not None and estimate.stock_source != "review" and item.expiry_date is None:
        expiry = (
            f"Примерно до {estimate.expiry:%d.%m.%Y} ({estimate.days} дн.)"
            f"\n   {escape(estimate.conditions)}"
        )
    question = (
        f"\n   ❓ {escape(item.clarification_question or '')}" if item.needs_clarification else ""
    )
    return (
        f"{index}. <b>{escape(item.name or item.visual_description)}</b>\n"
        f"   📦 {quantity}\n   📅 {expiry}{question}"
    )
