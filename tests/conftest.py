from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence
from datetime import date

import pytest

from zakupki import facts, marts
from zakupki.dimensions import build_customers, build_dates, build_suppliers
from zakupki.load import LoadResult, load_rows
from zakupki.store import Store

BASE: dict[str, str] = {
    "Реестровый номер": "К-1",
    "Дата контракта": "15.02.2026",
    "ИНН заказчика": "7701000001",
    "Заказчик": "ГБУЗ «Больница №1»",
    "Код региона": "77",
    "ИНН поставщика": "7712345678",
    "Поставщик": "ООО «Ромашка»",
    "ОКПД2": "62.01",
    "Предмет": "Поставка оборудования",
    "Начальная цена": "1000000,00",
    "Цена контракта": "900000,00",
    "Заявок": "3",
    "Способ закупки": "электронный аукцион",
}


def raw(**changes: str) -> dict[str, str]:
    """Строка выгрузки: по умолчанию исправная, изменения передаются по-русски же."""
    row = dict(BASE)
    for key, value in changes.items():
        row[COLUMN_BY_NAME[key]] = value
    return row


COLUMN_BY_NAME: dict[str, str] = {
    "number": "Реестровый номер",
    "signed": "Дата контракта",
    "customer_inn": "ИНН заказчика",
    "customer": "Заказчик",
    "region": "Код региона",
    "supplier_inn": "ИНН поставщика",
    "supplier": "Поставщик",
    "okpd": "ОКПД2",
    "subject": "Предмет",
    "start_price": "Начальная цена",
    "amount": "Цена контракта",
    "bids": "Заявок",
    "method": "Способ закупки",
}


def load(
    store: Store, rows: Sequence[dict[str, str]], *, source: str = "выгрузка.csv", force: bool = False
) -> LoadResult:
    digest = hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()
    return load_rows(store, rows, source=source, content_hash=digest, force=force)


def build_all(store: Store) -> None:
    build_dates(store)
    build_suppliers(store)
    build_customers(store)
    facts.build(store)
    marts.build(store)


def sample() -> list[dict[str, str]]:
    """Небольшой набор: три заказчика, три поставщика, переименование в середине периода."""
    return [
        raw(number="К-1", signed="15.01.2026", amount="900000,00"),
        raw(number="К-2", signed="20.02.2026", supplier_inn="7723456789", supplier="ООО «Ивтех»", amount="500000,00"),
        raw(
            number="К-3",
            signed="10.03.2026",
            customer_inn="7801000003",
            customer="СПб ГБУ «Дорожное хозяйство»",
            region="78",
            amount="1000000,00",
            method="единственный поставщик",
            bids="1",
        ),
        raw(number="К-4", signed="05.04.2026", supplier="ООО «Ромашка Плюс»", amount="800000,00"),
    ]


@pytest.fixture
def store() -> Iterator[Store]:
    warehouse = Store(":memory:")
    yield warehouse
    warehouse.close()


@pytest.fixture
def filled(store: Store) -> Store:
    """Хранилище с загруженным и собранным набором из `sample`."""
    load(store, sample())
    build_all(store)
    return store


TODAY = date(2026, 4, 20)
