"""Генератор выгрузки: синтетические закупки со всеми неприятностями настоящей выгрузки.

Открытые данные о закупках выкладываются целыми архивами и меняются, поэтому для проверок нужен свой
источник — воспроизводимый по зерну и заведомо содержащий то, что должно ломаться: пустые ИНН, суммы
прочерком, дубли строк, неизвестный регион, две записи одного контракта и переименование поставщика
посреди года (ради него, собственно, и нужна история измерений).
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final

from zakupki.rows import COLUMNS, money
from zakupki.schema import METHODS, OKPD

CUSTOMERS: Final = (
    ("7701000001", "ГБУЗ «Городская больница №1»", "77"),
    ("7702000002", "ГКУ «Центр информационных технологий»", "77"),
    ("7801000003", "СПб ГБУ «Дорожное хозяйство»", "78"),
    ("5001000004", "Администрация городского округа Химки", "50"),
    ("5201000005", "МБУ «Нижегородский транспорт»", "52"),
    ("1601000006", "ГАУЗ «Республиканская клиника»", "16"),
    ("6601000007", "МКУ «Городское благоустройство»", "66"),
    ("2401000008", "КГБУ «Красноярский энергоцентр»", "24"),
)

SUPPLIERS: Final = (
    ("7712345678", "ООО «Ромашка»"),
    ("7723456789", "ООО «Ивтех»"),
    ("7834567890", "АО «Невские системы»"),
    ("5045678901", "ООО «Химки-строй»"),
    ("5256789012", "ООО «Волга-сервис»"),
    ("1667890123", "ООО «Казань-медтехника»"),
    ("6678901234", "ООО «Урал-электро»"),
    ("2489012345", "АО «Сибирь-энерго»"),
    (
        "770123456789",
        "ИП Кузнецов А. В.",
    ),
    ("5490123456", "ООО «Новосибирский книжный дом»"),
)

RENAMED_SUPPLIER: Final = "7712345678"
RENAMED_SUPPLIER_NEW: Final = "ООО «Ромашка Плюс»"
RENAMED_CUSTOMER: Final = "7701000001"
RENAMED_CUSTOMER_NEW: Final = "ГБУЗ «Городская клиническая больница №1»"


@dataclass(frozen=True)
class Plan:
    """Что именно сгенерировать."""

    contracts: int = 400
    start: date = date(2026, 1, 15)
    days: int = 210
    seed: int = 7
    dirt: bool = True
    rename_after_day: int = 120
    customer_rename_after_day: int = 150
    subjects: tuple[str, ...] = field(
        default=(
            "Поставка компьютерного оборудования",
            "Сопровождение информационной системы",
            "Текущий ремонт помещений",
            "Поставка расходных материалов",
            "Услуги по уборке территории",
            "Перевозка пассажиров по маршруту",
            "Поставка тепловой энергии",
            "Разработка программного обеспечения",
        )
    )


def write_csv(path: Path, plan: Plan | None = None, *, encoding: str = "cp1251") -> int:
    """Пишет выгрузку и возвращает число строк в файле (вместе с грязными и дублями)."""
    settings = plan or Plan()
    lines = rows(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=encoding, newline="", errors="replace") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(COLUMNS), delimiter=";")
        writer.writeheader()
        writer.writerows(lines)
    return len(lines)


def rows(plan: Plan | None = None) -> list[dict[str, str]]:
    """Строки выгрузки в том виде, в каком их отдаёт система-источник: всё строками."""
    settings = plan or Plan()
    rng = random.Random(settings.seed)
    okpd_codes = list(OKPD)
    out: list[dict[str, str]] = []
    for number in range(settings.contracts):
        offset = rng.randrange(settings.days)
        signed = settings.start + timedelta(days=offset)
        customer_inn, customer_name, region = CUSTOMERS[rng.randrange(len(CUSTOMERS))]
        supplier_inn, supplier_name = SUPPLIERS[rng.randrange(len(SUPPLIERS))]
        if supplier_inn == RENAMED_SUPPLIER and offset >= settings.rename_after_day:
            supplier_name = RENAMED_SUPPLIER_NEW
        if customer_inn == RENAMED_CUSTOMER and offset >= settings.customer_rename_after_day:
            customer_name = RENAMED_CUSTOMER_NEW
        method = METHODS[rng.randrange(len(METHODS))]
        start_price = Decimal(rng.randrange(80, 9000)) * 1000
        discount = Decimal("1") if method == "единственный поставщик" else Decimal(rng.randrange(80, 100)) / 100
        amount = (start_price * discount).quantize(Decimal("0.01"))
        row = {
            "Реестровый номер": f"К-2026-{number + 1:05d}",
            "Дата контракта": _date_text(signed, rng, settings.dirt),
            "ИНН заказчика": customer_inn,
            "Заказчик": customer_name,
            "Код региона": region,
            "ИНН поставщика": supplier_inn,
            "Поставщик": supplier_name,
            "ОКПД2": okpd_codes[rng.randrange(len(okpd_codes))],
            "Предмет": settings.subjects[rng.randrange(len(settings.subjects))],
            "Начальная цена": _money_text(start_price, rng),
            "Цена контракта": _money_text(amount, rng),
            "Заявок": "1" if method == "единственный поставщик" else str(rng.randrange(1, 7)),
            "Способ закупки": method,
        }
        out.append(row)
        if settings.dirt:
            out.extend(_dirt(row, rng))
    return out


def _dirt(row: dict[str, str], rng: random.Random) -> list[dict[str, str]]:
    """Каждая порция грязи отвечает за свою проверку: разбор, дубли, справочники, качество."""
    extra: list[dict[str, str]] = []
    chance = rng.random()
    if chance < 0.03:  # пустой ИНН поставщика — строка не разберётся
        broken = dict(row)
        broken["Реестровый номер"] = row["Реестровый номер"] + "-Б"
        broken["ИНН поставщика"] = ""
        extra.append(broken)
    elif chance < 0.05:  # сумма прочерком
        broken = dict(row)
        broken["Реестровый номер"] = row["Реестровый номер"] + "-П"
        broken["Цена контракта"] = "—"
        extra.append(broken)
    elif chance < 0.07:  # неизвестный регион — разберётся, но не пройдёт проверку качества
        odd = dict(row)
        odd["Реестровый номер"] = row["Реестровый номер"] + "-Р"
        odd["Код региона"] = "99"
        extra.append(odd)
    elif chance < 0.09:  # цена выше начальной — повод для предупреждения
        odd = dict(row)
        odd["Реестровый номер"] = row["Реестровый номер"] + "-Ц"
        odd["Цена контракта"] = _money_text(money(row["Начальная цена"]) * 2, rng)
        extra.append(odd)
    elif chance < 0.12:  # тот же контракт второй строкой
        extra.append(dict(row))
    return extra


def _money_text(value: Decimal, rng: random.Random) -> str:
    """Половина выгрузок приходит с разделителями разрядов, половина — без.

    Разделитель — неразрывный пробел: именно он приезжает из отчётных систем и именно на нём
    ломается наивный `float(text)`.
    """
    plain = f"{value:.2f}".replace(".", ",")
    if rng.random() < 0.5:
        whole, _, fraction = plain.partition(",")
        groups = []
        while whole:
            groups.append(whole[-3:])
            whole = whole[:-3]
        plain = "\u00a0".join(reversed(groups)) + "," + fraction
    return plain


def _date_text(moment: date, rng: random.Random, dirt: bool) -> str:
    if dirt and rng.random() < 0.05:
        return moment.isoformat()
    return moment.strftime("%d.%m.%Y")
