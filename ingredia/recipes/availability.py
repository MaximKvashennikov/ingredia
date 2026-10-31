"""Deterministic stock checks with no pantry assumptions or expiry guarantees."""

from datetime import date
from decimal import Decimal

from ingredia.accounts.models import BatchView
from ingredia.recipes.models import Availability, Ingredient, IngredientView

UNIT_SCALE: dict[str, tuple[str, Decimal]] = {
    "g": ("mass", Decimal(1)),
    "kg": ("mass", Decimal(1000)),
    "ml": ("volume", Decimal(1)),
    "l": ("volume", Decimal(1000)),
    "pcs": ("count", Decimal(1)),
}


def name_key(name: str) -> str:
    """Compare explicit names conservatively without invented ingredient substitutions."""
    return " ".join(name.casefold().replace("ё", "е").split())


def check_ingredient(item: Ingredient, stock: list[BatchView], today: date) -> IngredientView:
    """Exclude expired batches and only sum compatible known dimensions."""
    matching = [row for row in stock if name_key(row.name) == name_key(item.name)]
    usable = [row for row in matching if row.expiry is None or row.expiry >= today]
    dimension, scale = UNIT_SCALE[item.unit]
    total = Decimal(0)
    unknown = False
    for row in usable:
        row_dimension, row_scale = UNIT_SCALE.get(row.unit or "", ("unknown", Decimal(1)))
        if row.quantity is None or row_dimension != dimension:
            unknown = True
            continue
        total += row.quantity * row_scale
    status = Availability.MISSING
    note = "Нет в холодильнике" if not matching else "Недостаточно; нужно докупить"
    if matching and not usable:
        note = "Срок всех подходящих партий истёк; не учитываются"
    if total >= Decimal(str(item.quantity)) * scale:
        status = Availability.AVAILABLE
        note = "Количество есть"
    elif unknown:
        status = Availability.CHECK
        note = "Проверьте количество или единицу измерения"
    if usable and status != Availability.MISSING:
        dates = []
        if any(row.expiry_source == "estimated" for row in usable):
            dates.append("срок по оценке")
        if any(row.expiry is None for row in usable):
            dates.append("срок неизвестен")
        if dates:
            note += "; " + ", ".join(dates)
    confirmed = [
        row.expiry
        for row in usable
        if row.expiry is not None and row.expiry_source in {"confirmed", "user"}
    ]
    return IngredientView(
        ingredient=item,
        status=status,
        note=note,
        confirmed_expiry=min(confirmed) if confirmed else None,
    )
