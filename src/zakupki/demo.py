"""Демонстрация: выгрузка, загрузка, «звезда», качество, витрины — и три отдельных сюжета.

Сюжеты, ради которых всё и написано:
1. тот же файл, загруженный второй раз, не даёт ни одной новой строки;
2. исправленная выгрузка перекрывает прежнюю версию контракта, а не добавляется к ней;
3. поставщик, сменивший название в середине года, получает вторую версию строки измерения, и старые
   контракты продолжают ссылаться на прежнее название.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from zakupki import facts, marts, quality, report
from zakupki.dimensions import build_customers, build_dates, build_suppliers
from zakupki.generate import RENAMED_SUPPLIER, Plan, write_csv
from zakupki.load import LoadResult, load_csv
from zakupki.store import Store


@dataclass(frozen=True, slots=True)
class DemoResult:
    root: Path
    text: str
    checks: list[quality.Check]


def run(*, root: Path | None = None, contracts: int = 400, seed: int = 7) -> DemoResult:
    base = Path(root) if root else Path(tempfile.mkdtemp(prefix="zakupki-demo-"))
    base.mkdir(parents=True, exist_ok=True)
    warehouse_path = base / "закупки.duckdb"
    warehouse_path.unlink(missing_ok=True)

    source = base / "выгрузка.csv"
    lines = write_csv(source, Plan(contracts=contracts, seed=seed))

    with Store(warehouse_path) as store:
        first = load_csv(store, source)
        again = load_csv(store, source)
        corrected = _corrected(store, base, source)

        build_dates(store)
        suppliers = build_suppliers(store)
        customers = build_customers(store)
        built = facts.build(store)
        sizes = marts.build(store)
        checks = quality.run(store)

        text = "\n".join(
            [
                f"Выгрузка: {lines} строк в файле {source.name} (кодировка Windows-1251).",
                first.line,
                again.line,
                corrected.line,
                "",
                f"Измерения: поставщиков — новых {suppliers.added}, с новой версией {suppliers.changed}; "
                f"заказчиков — новых {customers.added}, с новой версией {customers.changed}.",
                built.line,
                "Витрины: " + ", ".join(f"{name} — {rows} строк" for name, rows in sizes.items()) + ".",
                "",
                report.summary(store, checks),
                "",
                "История поставщика, сменившего название:",
                report.history_table(store, RENAMED_SUPPLIER),
                "",
                "Помесячно:",
                report.months_table(store),
                "",
                f"Файлы демонстрации: {base}",
            ]
        )
    return DemoResult(root=base, text=text, checks=checks)


def _corrected(store: Store, base: Path, source: Path) -> LoadResult:
    """Исправленная выгрузка: у первого контракта изменилась сумма — так бывает при доп. соглашении."""
    text = source.read_bytes().decode("cp1251").splitlines()
    if len(text) < 2:
        return LoadResult(batch_id=0, source="исправление", total=0, accepted=0, rejected=0, duplicates=0)
    header, first, *rest = text
    cells = first.split(";")
    price_index = header.split(";").index("Цена контракта")
    cells[price_index] = (
        f"{Decimal(cells[price_index].replace(chr(160), '').replace(' ', '').replace(',', '.')) / 2:.2f}".replace(
            ".", ","
        )
    )
    fixed = base / "выгрузка-исправленная.csv"
    fixed.write_bytes("\n".join([header, ";".join(cells), *rest]).encode("cp1251", errors="replace"))
    return load_csv(store, fixed)
