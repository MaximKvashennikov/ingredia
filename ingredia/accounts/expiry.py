"""Справочные оценки хранения, отделённые от подтверждённых дат на упаковке."""

import json
import re
from datetime import date, timedelta
from functools import lru_cache
from importlib.resources import files
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ingredia.recognition.models import ProductObservation


class ExpiryRule(BaseModel):
    """Описать справочное правило хранения с условиями и источником.

    Attributes:
        id: Стабильный идентификатор правила в справочнике.
        names: Названия и словосочетания для сопоставления с продуктом.
        days: Справочное количество дней хранения от опорной даты.
        conditions: Условия применимости оценки, включая способ хранения.
        source: Ссылка или внутренний идентификатор источника правила.
        exclude: Фрагменты названия, запрещающие применение правила.
    """

    id: str
    names: list[str]
    days: int = Field(ge=1, le=365)
    conditions: str
    source: str
    exclude: list[str] = Field(default_factory=list)


class ExpiryEstimate(BaseModel):
    """Хранить оценку срока или дату проверки с объяснением расчёта.

    Attributes:
        expiry: Рассчитанная дата хранения или проверки продукта.
        reference_date: Опорная дата, от которой отсчитаны дни.
        days: Количество дней между опорной и рассчитанной датами.
        rule_id: Идентификатор применённого правила или политики проверки.
        conditions: Условия оценки и оговорка о неизвестной дате покупки при необходимости.
        source: Источник справочного правила либо внутренней политики.
    """

    model_config = ConfigDict(extra="forbid")
    expiry: date
    reference_date: date
    days: int = Field(ge=1, le=365)
    rule_id: str
    conditions: str
    source: str

    @property
    def stock_source(self) -> Literal["estimated", "review"]:
        """Определить происхождение рассчитанной даты для сохранения партии.

        Returns:
            review для даты проверки неизвестной категории; estimated для справочной оценки хранения.
        """
        return "review" if self.rule_id == "unclassified-review-v1" else "estimated"

    @model_validator(mode="after")
    def consistent_date(self) -> "ExpiryEstimate":
        """Проверить согласованность рассчитанной и опорной дат.

        Returns:
            Текущая модель после успешной проверки.

        Raises:
            ValueError: Рассчитанная дата не совпадает с опорной датой плюс количество дней.
        """
        if self.expiry != self.reference_date + timedelta(days=self.days):
            raise ValueError("Inconsistent estimate date")
        return self


@lru_cache
def rules() -> list[ExpiryRule]:
    """Загрузить и закешировать версионируемый справочник сроков хранения.

    Returns:
        Список проверенных моделей правил из ресурса expiry_v2.json.
    """
    resource = files("ingredia.accounts").joinpath("data/expiry_v2.json")
    return [ExpiryRule.model_validate(item) for item in json.loads(resource.read_text("utf-8"))]


def name_key(value: str) -> str:
    """Нормализовать название для сопоставления с фразами справочника.

    Args:
        value: Исходное название или словосочетание для сравнения.

    Returns:
        Строка в нижнем регистре с заменой «ё» на «е» и разделителей на одиночные пробелы.
    """
    return " ".join(re.sub(r"[^\w]+", " ", value.casefold().replace("ё", "е")).split())


def estimate_name(
    name: str, reference_date: date, unknown_age: bool = False
) -> ExpiryEstimate | None:
    """Подобрать справочный срок без выдуманной даты для неизвестной категории.

    Args:
        name: Название продукта с возможными брендом, фасовкой и признаками обработки.
        reference_date: Опорная дата покупки или оценки для расчёта срока.
        unknown_age: Признак неизвестной даты покупки, который добавляет оговорку в условия.

    Returns:
        Справочная оценка по наиболее конкретной фразе или None, если подходящего правила нет.
    """
    normalized = name_key(name)
    matches: list[tuple[int, ExpiryRule]] = []
    for rule in rules():
        if any(part in normalized for part in rule.exclude):
            continue
        for alias in rule.names:
            key = name_key(alias)
            if f" {key} " in f" {normalized} ":
                matches.append((len(key), rule))
    if not matches:
        return None
    rule = max(matches, key=lambda item: item[0])[1]
    conditions = rule.conditions
    if unknown_age:
        conditions += "; дата покупки неизвестна, отсчёт от даты оценки"
    return ExpiryEstimate(
        expiry=reference_date + timedelta(days=rule.days),
        reference_date=reference_date,
        days=rule.days,
        rule_id=rule.id,
        conditions=conditions,
        source=rule.source,
    )


def estimate_expiry(product: ProductObservation, reference_date: date) -> ExpiryEstimate | None:
    """Оценить срок распознанного продукта, если ему не требуется уточнение.

    Args:
        product: Распознанный продукт с названием, явной датой и признаком уточнения.
        reference_date: Опорная дата для расчёта справочного срока.

    Returns:
        Справочная оценка срока. None возвращается при явной дате, отсутствии правила,
        неизвестном названии или необходимости уточнить продукт.
    """
    if product.expiry_date is not None or product.needs_clarification or product.name is None:
        return None
    return estimate_name(product.name, reference_date)
