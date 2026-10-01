from __future__ import annotations

import pytest

from zakupki import marts, report
from zakupki.store import Store


def test_region_mart_groups_by_region(filled: Store) -> None:
    rows = {str(row[0]): row for row in filled.query("SELECT region_name, contracts, amount FROM mart_region")}
    assert rows["Москва"][1] == 3
    assert str(rows["Санкт-Петербург"][2]) == "1000000.00"


def test_supplier_mart_shows_the_current_name(filled: Store) -> None:
    name, contracts, customers = filled.one(
        "SELECT supplier_name, contracts, customers FROM mart_supplier WHERE inn = '7712345678'"
    )
    assert name == "ООО «Ромашка Плюс»", "в витрине — нынешнее название, в факте — историческое"
    assert (contracts, customers) == (3, 2)


def test_month_mart_speaks_russian(filled: Store) -> None:
    months = [row[0] for row in filled.query("SELECT month_name FROM mart_month ORDER BY year, month")]
    assert months == ["январь", "февраль", "март", "апрель"]


def test_single_supplier_share_is_counted(filled: Store) -> None:
    share = filled.one("SELECT single_share FROM mart_region WHERE region_name = 'Санкт-Петербург'")[0]
    assert share == pytest.approx(1.0), "единственный контракт региона заключён с единственным поставщиком"


def test_marts_are_rebuilt_not_appended(filled: Store) -> None:
    first = marts.build(filled)
    second = marts.build(filled)
    assert first == second


def test_report_tables_are_readable(filled: Store) -> None:
    regions = report.regions_table(filled)
    assert "Москва" in regions
    assert "Экономия" in regions

    history = report.history_table(filled, "7712345678")
    assert "ООО «Ромашка»" in history
    assert "по сей день" in history
    assert report.history_table(filled, "0000000000").startswith("ИНН 0000000000")


def test_money_is_formatted_for_humans() -> None:
    assert report.money("1234567.89") == "1 234 568"
    assert report.share(0.1234) == "12.3%"
