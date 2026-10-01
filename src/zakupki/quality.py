"""Проверки качества: двенадцать правил вместо одного «в таблице есть хоть что-то».

Проверка вида `SELECT COUNT(*) FROM {table}` ловит только пустую таблицу. Ноль строк — это, конечно, беда, но куда чаще
беда выглядит иначе: факт есть, а ключей в нём нет;
суммы разошлись со слоем stage; поставщик числится в двух текущих версиях сразу.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Final

from zakupki.schema import LATEST_STAGE
from zakupki.store import Store

ERROR: Final = "ошибка"
WARNING: Final = "внимание"
FRESH_DAYS: Final = 90


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    level: str
    ok: bool
    detail: str

    @property
    def mark(self) -> str:
        if self.ok:
            return "+"
        return "!" if self.level == ERROR else "·"

    def line(self) -> str:
        return f"{self.mark} {self.name}: {self.detail}"


def run(store: Store, *, fresh_days: int = FRESH_DAYS, today: date | None = None) -> list[Check]:
    """Прогоняет все проверки по собранному факту и измерениям."""
    moment = today or datetime.now(UTC).date()
    checks = [
        _not_empty(store),
        _keys_resolved(store),
        _unique_contracts(store),
        _rows_match_stage(store),
        _amounts_match_stage(store),
        _regions_known(store),
        _dates_in_calendar(store),
        _history_consistent(store, "dim_supplier", "поставщиков"),
        _history_consistent(store, "dim_customer", "заказчиков"),
        _price_not_above_start(store),
        _bids_present(store),
        _fresh(store, moment, fresh_days),
        _rejected_rows(store),
    ]
    return checks


def errors(checks: list[Check]) -> list[Check]:
    return [check for check in checks if not check.ok and check.level == ERROR]


def warnings(checks: list[Check]) -> list[Check]:
    return [check for check in checks if not check.ok and check.level == WARNING]


def _not_empty(store: Store) -> Check:
    rows = store.count("fact_contract")
    return Check("факт не пуст", ERROR, rows > 0, f"строк в факте {rows}")


def _keys_resolved(store: Store) -> Check:
    broken = store.count("fact_contract", "customer_key IS NULL OR supplier_key IS NULL")
    detail = "у всех строк есть заказчик и поставщик" if not broken else f"строк без ключа измерения: {broken}"
    return Check("ключи измерений подставлены", ERROR, broken == 0, detail)


def _unique_contracts(store: Store) -> Check:
    total = store.count("fact_contract")
    unique = int(store.one("SELECT count(DISTINCT registry_number) FROM fact_contract")[0])
    detail = f"реестровых номеров {unique} из {total}"
    return Check("реестровый номер уникален", ERROR, total == unique, detail)


def _rows_match_stage(store: Store) -> Check:
    fact = store.count("fact_contract")
    stage = int(store.one(f"SELECT count(*) FROM ({LATEST_STAGE})")[0])  # noqa: S608 — константа пакета
    detail = f"в факте {fact}, в stage {stage}"
    return Check("строк столько же, сколько в stage", ERROR, fact == stage, detail)


def _amounts_match_stage(store: Store) -> Check:
    fact = store.one("SELECT coalesce(sum(amount), 0) FROM fact_contract")[0]
    stage = store.one(f"SELECT coalesce(sum(amount), 0) FROM ({LATEST_STAGE})")[0]  # noqa: S608 — константа пакета
    same = Decimal(str(fact)) == Decimal(str(stage))
    return Check("суммы сходятся со stage", ERROR, same, f"факт {_money(fact)}, stage {_money(stage)}")


def _regions_known(store: Store) -> Check:
    unknown = store.query(
        """
        SELECT DISTINCT f.region_code FROM fact_contract f
        LEFT JOIN dim_region r ON r.region_code = f.region_code
        WHERE r.region_code IS NULL
        """
    )
    codes = ", ".join(str(row[0]) for row in unknown)
    detail = "все коды регионов есть в справочнике" if not unknown else f"неизвестные коды: {codes}"
    return Check("регионы есть в справочнике", ERROR, not unknown, detail)


def _dates_in_calendar(store: Store) -> Check:
    missing = int(
        store.one(
            """
            SELECT count(*) FROM fact_contract f
            LEFT JOIN dim_date d ON d.date_key = f.signed_on
            WHERE d.date_key IS NULL
            """
        )[0]
    )
    detail = "календарь покрывает все даты" if not missing else f"дат вне календаря: {missing}"
    return Check("даты есть в календаре", ERROR, missing == 0, detail)


def _history_consistent(store: Store, table: str, what: str) -> Check:
    overlaps = int(
        store.one(
            f"""
            SELECT count(*) FROM (
                SELECT inn, valid_from,
                       lag(valid_to) OVER (PARTITION BY inn ORDER BY valid_from) AS previous_to
                FROM {table}
            ) WHERE previous_to IS NOT NULL AND valid_from < previous_to
            """  # noqa: S608 — имя таблицы приходит из этого же модуля
        )[0]
    )
    doubles = int(
        store.one(
            f"SELECT count(*) FROM (SELECT inn FROM {table} WHERE is_current GROUP BY inn HAVING count(*) <> 1)"  # noqa: S608
        )[0]
    )
    ok = overlaps == 0 and doubles == 0
    detail = "интервалы не пересекаются, текущая версия одна" if ok else f"пересечений {overlaps}, дублей {doubles}"
    return Check(f"история {what} непротиворечива", ERROR, ok, detail)


def _price_not_above_start(store: Store) -> Check:
    above = store.count("fact_contract", "amount > start_price")
    detail = "цена нигде не выше начальной" if not above else f"контрактов дороже начальной цены: {above}"
    return Check("цена не выше начальной", WARNING, above == 0, detail)


def _bids_present(store: Store) -> Check:
    empty = store.count("fact_contract", "bids < 1")
    detail = "везде хотя бы одна заявка" if not empty else f"контрактов без заявок: {empty}"
    return Check("заявки указаны", WARNING, empty == 0, detail)


def _fresh(store: Store, today: date, fresh_days: int) -> Check:
    last = store.one("SELECT max(signed_on) FROM fact_contract")[0]
    if last is None:
        return Check("данные свежие", WARNING, False, "в факте нет ни одной даты")
    age = (today - last).days
    return Check(
        "данные свежие", WARNING, age <= fresh_days, f"последний контракт {last:%d.%m.%Y}, это {age} дн. назад"
    )


def _rejected_rows(store: Store) -> Check:
    rejected = store.count("stage_rejected")
    detail = "все строки выгрузки разобраны" if not rejected else f"строк не разобрано: {rejected}"
    return Check("выгрузка разобрана целиком", WARNING, rejected == 0, detail)


def _money(value: object) -> str:
    return f"{Decimal(str(value)):,.2f}".replace(",", " ")
