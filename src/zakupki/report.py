"""Отчёты в консоль: загрузки, качество, витрины и история одной организации."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from zakupki.quality import Check
from zakupki.store import Batch, Store


def table(headers: Sequence[str], rows: Sequence[Sequence[str]], align: str = "") -> str:
    columns = len(headers)
    widths = [len(header) for header in headers]
    for row in rows:
        for index in range(columns):
            widths[index] = max(widths[index], len(row[index]))
    rules = (align + "l" * columns)[:columns]

    def render(cells: Sequence[str]) -> str:
        parts = [
            cells[index].rjust(widths[index]) if rules[index] == "r" else cells[index].ljust(widths[index])
            for index in range(columns)
        ]
        return "  ".join(parts).rstrip()

    return "\n".join([render(headers), *(render(row) for row in rows)])


def money(value: object) -> str:
    """Рубли без копеек и с пробелом между разрядами: в отчёте копейки только мешают."""
    return f"{Decimal(str(value)):,.0f}".replace(",", " ")


def share(value: object) -> str:
    number = float(str(value)) if value is not None else 0.0
    return f"{number * 100:.1f}%"


def batches_table(batches: Sequence[Batch]) -> str:
    rows = [
        [
            str(batch.batch_id),
            batch.source,
            f"{batch.loaded_at:%d.%m %H:%M}",
            str(batch.rows_total),
            str(batch.rows_accepted),
            str(batch.rows_rejected),
        ]
        for batch in batches
    ]
    return table(["№", "Файл", "Загружено", "Строк", "Принято", "Отброшено"], rows, align="lll" + "r" * 3)


def quality_block(checks: Sequence[Check]) -> str:
    lines = [check.line() for check in checks]
    failed = [check for check in checks if not check.ok]
    lines.append("")
    if not failed:
        lines.append("Все проверки пройдены.")
    else:
        lines.append(f"Не пройдено проверок: {len(failed)} из {len(checks)}.")
    return "\n".join(lines)


def regions_table(store: Store, limit: int = 10) -> str:
    rows = store.query(
        "SELECT region_name, contracts, amount, savings, savings_share, single_share "
        "FROM mart_region ORDER BY amount DESC LIMIT ?",
        [limit],
    )
    body = [[str(row[0]), str(row[1]), money(row[2]), money(row[3]), share(row[4]), share(row[5])] for row in rows]
    headers = ["Регион", "Контрактов", "Сумма, ₽", "Экономия, ₽", "Экономия", "У единственного"]
    return table(headers, body, align="l" + "r" * 5)


def suppliers_table(store: Store, limit: int = 10) -> str:
    rows = store.query(
        "SELECT supplier_name, inn, contracts, customers, amount, savings_share "
        "FROM mart_supplier ORDER BY amount DESC LIMIT ?",
        [limit],
    )
    body = [[str(row[0]), str(row[1]), str(row[2]), str(row[3]), money(row[4]), share(row[5])] for row in rows]
    return table(["Поставщик", "ИНН", "Контрактов", "Заказчиков", "Сумма, ₽", "Экономия"], body, align="ll" + "r" * 4)


def months_table(store: Store) -> str:
    rows = store.query(
        "SELECT year, month_name, contracts, amount, savings_share, single_contracts "
        "FROM mart_month ORDER BY year, month"
    )
    body = [[str(row[0]), str(row[1]), str(row[2]), money(row[3]), share(row[4]), str(row[5])] for row in rows]
    return table(["Год", "Месяц", "Контрактов", "Сумма, ₽", "Экономия", "У единственного"], body, align="ll" + "r" * 4)


def history_table(store: Store, inn: str) -> str:
    """История одной организации: ради этого в измерениях и заведены сроки действия."""
    supplier = store.query(
        "SELECT 'поставщик', name, valid_from, valid_to, is_current "
        "FROM dim_supplier WHERE inn = ? ORDER BY valid_from",
        [inn],
    )
    customer = store.query(
        "SELECT 'заказчик', name, valid_from, valid_to, is_current FROM dim_customer WHERE inn = ? ORDER BY valid_from",
        [inn],
    )
    rows = [*supplier, *customer]
    if not rows:
        return f"ИНН {inn} в хранилище не встречается."
    body = [
        [
            str(row[0]),
            str(row[1]),
            f"{row[2]:%d.%m.%Y}",
            "по сей день" if bool(row[4]) else f"{row[3]:%d.%m.%Y}",
            "да" if bool(row[4]) else "нет",
        ]
        for row in rows
    ]
    return table(["Роль", "Наименование", "Действует с", "По", "Текущая"], body)


def summary(store: Store, checks: Sequence[Check]) -> str:
    facts = store.count("fact_contract")
    stage = store.count("stage_contract")
    amount = store.one("SELECT coalesce(sum(amount), 0) FROM fact_contract")[0]
    parts = [
        f"Хранилище: строк в stage {stage}, в факте {facts}, сумма контрактов {money(amount)} ₽.",
        "",
        "Загрузки:",
        batches_table(store.batches()),
        "",
        "Качество:",
        quality_block(checks),
        "",
        "Регионы:",
        regions_table(store),
        "",
        "Поставщики:",
        suppliers_table(store, limit=5),
    ]
    return "\n".join(parts)
