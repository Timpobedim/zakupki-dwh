"""Разбор строки выгрузки: деньги, даты, ИНН — и понятная причина, если строка не годится.

Выгрузки приходят такими, какими их отдаёт система-источник: суммы с пробелами и запятой, даты то
в одном формате, то в другом, пустые ИНН. Строка, которую не удалось разобрать, не молчит: она
попадает в отдельную таблицу с указанием поля и причины, и её видно в отчёте о загрузке.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Final

SPACES: Final = ("\u00a0", "\u202f", "\u2009", " ")
"""Неразрывный, узкий неразрывный, тонкий и обычный пробелы — в выгрузках встречаются все четыре."""

DATE_FORMATS: Final = ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y")
CENTS: Final = Decimal("0.01")

COLUMNS: Final = (
    "Реестровый номер",
    "Дата контракта",
    "ИНН заказчика",
    "Заказчик",
    "Код региона",
    "ИНН поставщика",
    "Поставщик",
    "ОКПД2",
    "Предмет",
    "Начальная цена",
    "Цена контракта",
    "Заявок",
    "Способ закупки",
)


@dataclass(frozen=True, slots=True)
class Contract:
    """Разобранная строка выгрузки."""

    registry_number: str
    signed_on: date
    customer_inn: str
    customer_name: str
    region_code: str
    supplier_inn: str
    supplier_name: str
    okpd_code: str
    subject: str
    start_price: Decimal
    amount: Decimal
    bids: int
    method: str

    def row(self, batch_id: int) -> tuple[object, ...]:
        return (
            batch_id,
            self.registry_number,
            self.signed_on,
            self.customer_inn,
            self.customer_name,
            self.region_code,
            self.supplier_inn,
            self.supplier_name,
            self.okpd_code,
            self.subject,
            self.start_price,
            self.amount,
            self.bids,
            self.method,
        )


@dataclass(frozen=True, slots=True)
class Problem:
    """Почему строка не попала в хранилище."""

    row_number: int
    field: str
    reason: str
    raw: str

    def row(self, batch_id: int) -> tuple[object, ...]:
        return (batch_id, self.row_number, self.field, self.reason, self.raw[:200])


class FieldError(ValueError):
    """Одно поле строки разобрать не удалось."""


def money(text: str) -> Decimal:
    """«1 234 567,89» → Decimal('1234567.89'). Копейки округляются, мусор — ошибка."""
    cleaned = text.strip()
    for space in SPACES:
        cleaned = cleaned.replace(space, "")
    cleaned = cleaned.replace(",", ".").replace("руб.", "").replace("₽", "")
    if not cleaned or cleaned in {"-", "—", "нет"}:
        raise FieldError("пусто")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise FieldError(f"не похоже на сумму: «{text.strip()}»") from exc
    if value < 0:
        raise FieldError(f"отрицательная сумма: «{text.strip()}»")
    return value.quantize(CENTS)


def day(text: str) -> date:
    """Дата в любом из трёх форматов, которые встречаются в выгрузках."""
    cleaned = text.strip()
    if not cleaned:
        raise FieldError("пусто")
    for template in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, template).date()  # noqa: DTZ007 — это календарная дата, не момент
        except ValueError:
            continue
    raise FieldError(f"непонятная дата: «{cleaned}»")


def inn(text: str) -> str:
    """ИНН юридического лица — десять цифр, индивидуального предпринимателя — двенадцать."""
    cleaned = text.strip().replace(" ", "")
    if not cleaned:
        raise FieldError("пусто")
    if not cleaned.isdigit() or len(cleaned) not in {10, 12}:
        raise FieldError(f"ИНН должен быть из 10 или 12 цифр, получено «{cleaned}»")
    return cleaned


def count(text: str) -> int:
    cleaned = text.strip()
    if not cleaned:
        return 0
    if not cleaned.isdigit():
        raise FieldError(f"ожидалось целое число, получено «{cleaned}»")
    return int(cleaned)


def text_value(raw: Mapping[str, str], column: str) -> str:
    value = str(raw.get(column, "")).strip()
    if not value:
        raise FieldError("пусто")
    return value


def parse(raw: Mapping[str, str], row_number: int) -> tuple[Contract | None, Problem | None]:
    """Разбирает строку. Либо контракт, либо причина, по которой строки в хранилище не будет."""
    field = ""
    try:
        field = "Реестровый номер"
        registry_number = text_value(raw, field)
        field = "Дата контракта"
        signed_on = day(raw.get(field, ""))
        field = "ИНН заказчика"
        customer_inn = inn(raw.get(field, ""))
        field = "Заказчик"
        customer_name = text_value(raw, field)
        field = "Код региона"
        region_code = text_value(raw, field)
        field = "ИНН поставщика"
        supplier_inn = inn(raw.get(field, ""))
        field = "Поставщик"
        supplier_name = text_value(raw, field)
        field = "ОКПД2"
        okpd_code = text_value(raw, field)
        field = "Предмет"
        subject = text_value(raw, field)
        field = "Начальная цена"
        start_price = money(raw.get(field, ""))
        field = "Цена контракта"
        amount = money(raw.get(field, ""))
        field = "Заявок"
        bids = count(raw.get(field, ""))
        field = "Способ закупки"
        method = text_value(raw, field)
    except FieldError as exc:
        return None, Problem(row_number=row_number, field=field, reason=str(exc), raw=_line(raw))
    contract = Contract(
        registry_number=registry_number,
        signed_on=signed_on,
        customer_inn=customer_inn,
        customer_name=customer_name,
        region_code=region_code,
        supplier_inn=supplier_inn,
        supplier_name=supplier_name,
        okpd_code=okpd_code,
        subject=subject,
        start_price=start_price,
        amount=amount,
        bids=bids,
        method=method,
    )
    return contract, None


def _line(raw: Mapping[str, str]) -> str:
    return ";".join(str(raw.get(column, "")) for column in COLUMNS)
