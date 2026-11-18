"""Компактный список холодильника и полные карточки продуктов."""

from html import escape

from aiogram.types import (
    InputRichBlockParagraph,
    InputRichMessage,
    RichMessageButton,
    RichTextBold,
    RichTextButton,
)

from ingredia.accounts.models import BatchView, StockPage
from ingredia.adapters.telegram.views import stock_card, stock_expiry_text, unit_label
from ingredia.clock import current_date

PRODUCT_NAME_LIMIT = 18


def _product_label(name: str) -> str:
    """Сократить название для списка, сохранив исходные данные продукта.

    Args:
        name: Полное название продукта, включая возможные пробелы и переводы строк.

    Returns:
        Название с нормализованными пробелами длиной до 18 символов включительно.
        При сокращении последний символ заменяется многоточием.
    """
    label = " ".join(name.split())
    if len(label) <= PRODUCT_NAME_LIMIT:
        return label
    return label[: PRODUCT_NAME_LIMIT - 1].rstrip() + "…"


def stock_content(stock: StockPage, banner: str = "") -> InputRichMessage:
    """Сформировать страницу холодильника с компактными действиями в строках.

    Args:
        stock: Страница запасов с продуктами, общим количеством и номером страницы от нуля.
        banner: Необязательное уведомление, которое размещается перед заголовком списка.

    Returns:
        Rich-сообщение с вертикальными блоками продуктов или подсказкой для пустого холодильника.
        Названия передаются как текст без интерпретации пользовательской разметки.
    """
    blocks: list[InputRichBlockParagraph] = []
    if banner:
        blocks.append(InputRichBlockParagraph(text=banner.strip()))
    if not stock.items:
        blocks.append(InputRichBlockParagraph(text=RichTextBold(text="Холодильник пуст")))
        blocks.append(
            InputRichBlockParagraph(
                text="Добавьте покупки: фото чека, фото продуктов или текстовый список.",
            )
        )
        return InputRichMessage(blocks=[*blocks], skip_entity_detection=True)
    blocks.extend(
        [
            InputRichBlockParagraph(text=RichTextBold(text="Мой холодильник")),
            InputRichBlockParagraph(
                text=f"{stock.total} поз. · Страница {stock.page + 1} из {(stock.total + 5) // 6}"
            ),
            InputRichBlockParagraph(text="Сортировка по сроку годности"),
        ]
    )
    for item in stock.items:
        quantity = (
            f"{item.quantity.normalize():f} {unit_label(item.unit)}"
            if item.quantity
            else "Количество не указано"
        )
        warning = (
            "⚠️ "
            if item.expiry and item.expiry_source != "review" and item.expiry < current_date()
            else ""
        )
        blocks.append(
            InputRichBlockParagraph(
                text=[
                    warning,
                    RichTextButton(
                        button=RichMessageButton(
                            text=_product_label(item.name),
                            style="link",
                            callback_data=f"stock:{item.id}:{stock.page}",
                        )
                    ),
                    f"\n📦 {quantity}\n📅 {stock_expiry_text(item)}\n",
                    RichTextButton(
                        button=RichMessageButton(
                            text="Удалить ❌",
                            style="link",
                            callback_data=f"del:{item.id}:{stock.page}:{item.version}",
                        )
                    ),
                ],
            )
        )
    return InputRichMessage(blocks=[*blocks], skip_entity_detection=True)


def stock_details(item: BatchView, page: str) -> InputRichMessage:
    """Сформировать полную карточку продукта с кнопкой удаления.

    Args:
        item: Партия продукта с полным названием, количеством и происхождением срока.
        page: Номер страницы холодильника от нуля, сохранённый в callback удаления.

    Returns:
        Rich-сообщение с экранированной HTML-карточкой и действием «Удалить ❌».
    """
    paragraphs = "".join(f"<p>{line}</p>" for line in stock_card(item).splitlines() if line)
    data = escape(f"del:{item.id}:{page}:{item.version}", quote=True)
    return InputRichMessage(
        html=paragraphs
        + f'<p><tg-button type="callback_data" style="link" data="{data}">Удалить ❌</tg-button></p>',
        skip_entity_detection=True,
    )
