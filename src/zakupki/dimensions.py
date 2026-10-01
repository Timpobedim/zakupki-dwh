"""Измерения: календарь и история изменений (SCD2).

Заказчик переименовался — контракты прошлого года должны остаться под прежним названием. Для этого
у строки измерения есть срок действия: интервал `[valid_from, valid_to)` и признак «текущая».
Факт подбирает ту версию, которая действовала на дату контракта.

Таблицы не пересоздаются при каждом запуске, поэтому переименование не переписывает историю.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

from zakupki.schema import FAR_FUTURE, LATEST_STAGE
from zakupki.store import Store

MONTHS: Final = (
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)


@dataclass(frozen=True, slots=True)
class ChangeReport:
    """Что случилось с измерением при построении."""

    added: int = 0
    changed: int = 0
    unchanged: int = 0
    ignored: int = 0

    @property
    def total(self) -> int:
        return self.added + self.changed + self.unchanged + self.ignored


def build_dates(store: Store) -> int:
    """Календарь строится по диапазону дат в stage — ни одного лишнего дня."""
    first, last = store.one("SELECT min(signed_on), max(signed_on) FROM stage_contract")
    if first is None or last is None:
        return 0
    days = [first + timedelta(days=number) for number in range((last - first).days + 1)]
    store.executemany(
        "INSERT INTO dim_date VALUES (?,?,?,?,?,?) ON CONFLICT (date_key) DO NOTHING",
        [[day, day.year, (day.month - 1) // 3 + 1, day.month, MONTHS[day.month - 1], day.day] for day in days],
    )
    return len(days)


def build_suppliers(store: Store) -> ChangeReport:
    """История поставщиков: ключ — ИНН, меняющийся признак — наименование."""
    versions = store.query(
        f"""
        WITH latest AS ({LATEST_STAGE})
        SELECT supplier_inn, supplier_name, min(signed_on) AS first_seen
        FROM latest GROUP BY 1, 2 ORDER BY 1, 3
        """  # noqa: S608 — запрос собран из константы модуля, снаружи в него ничего не попадает
    )
    added = changed = unchanged = ignored = 0
    for inn, name, first_seen in versions:
        current = store.query("SELECT supplier_key, valid_from FROM dim_supplier WHERE inn = ? AND is_current", [inn])
        if not current:
            store.execute(
                "INSERT INTO dim_supplier VALUES (nextval('seq_supplier'), ?, ?, ?, ?, TRUE)",
                [inn, name, first_seen, FAR_FUTURE],
            )
            added += 1
            continue
        key, valid_from = current[0]
        if _known_supplier(store, inn, name):
            unchanged += 1
            continue
        if not _later(first_seen, valid_from):
            ignored += 1
            continue
        store.execute(
            "UPDATE dim_supplier SET valid_to = ?, is_current = FALSE WHERE supplier_key = ?", [first_seen, key]
        )
        store.execute(
            "INSERT INTO dim_supplier VALUES (nextval('seq_supplier'), ?, ?, ?, ?, TRUE)",
            [inn, name, first_seen, FAR_FUTURE],
        )
        changed += 1
    return ChangeReport(added=added, changed=changed, unchanged=unchanged, ignored=ignored)


def build_customers(store: Store) -> ChangeReport:
    """История заказчиков: ключ — ИНН, меняющиеся признаки — наименование и регион."""
    versions = store.query(
        f"""
        WITH latest AS ({LATEST_STAGE})
        SELECT customer_inn, customer_name, region_code, min(signed_on) AS first_seen
        FROM latest GROUP BY 1, 2, 3 ORDER BY 1, 4
        """  # noqa: S608 — запрос собран из константы модуля, снаружи в него ничего не попадает
    )
    added = changed = unchanged = ignored = 0
    for inn, name, region_code, first_seen in versions:
        current = store.query("SELECT customer_key, valid_from FROM dim_customer WHERE inn = ? AND is_current", [inn])
        if not current:
            store.execute(
                "INSERT INTO dim_customer VALUES (nextval('seq_customer'), ?, ?, ?, ?, ?, TRUE)",
                [inn, name, region_code, first_seen, FAR_FUTURE],
            )
            added += 1
            continue
        key, valid_from = current[0]
        if _known_customer(store, inn, name, region_code):
            unchanged += 1
            continue
        if not _later(first_seen, valid_from):
            ignored += 1
            continue
        store.execute(
            "UPDATE dim_customer SET valid_to = ?, is_current = FALSE WHERE customer_key = ?", [first_seen, key]
        )
        store.execute(
            "INSERT INTO dim_customer VALUES (nextval('seq_customer'), ?, ?, ?, ?, ?, TRUE)",
            [inn, name, region_code, first_seen, FAR_FUTURE],
        )
        changed += 1
    return ChangeReport(added=added, changed=changed, unchanged=unchanged, ignored=ignored)


def _later(first_seen: date, valid_from: date) -> bool:
    """Версия из прошлого историю не переписывает: интервалы должны идти вперёд, а не назад."""
    return first_seen > valid_from


def _known_supplier(store: Store, inn: str, name: str) -> bool:
    """Такое название у этого ИНН уже встречалось — это повтор, а не новая версия."""
    return bool(store.query("SELECT 1 FROM dim_supplier WHERE inn = ? AND name = ? LIMIT 1", [inn, name]))


def _known_customer(store: Store, inn: str, name: str, region_code: str) -> bool:
    """То же для заказчика: сверяются и наименование, и регион."""
    return bool(
        store.query(
            "SELECT 1 FROM dim_customer WHERE inn = ? AND name = ? AND region_code = ? LIMIT 1",
            [inn, name, region_code],
        )
    )
