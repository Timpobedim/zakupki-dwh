from __future__ import annotations

from datetime import date

from conftest import load, raw, sample

from zakupki.dimensions import build_customers, build_dates, build_suppliers
from zakupki.store import Store


def test_calendar_covers_exactly_the_loaded_range(store: Store) -> None:
    load(store, sample())
    days = build_dates(store)
    first, last = store.one("SELECT min(date_key), max(date_key) FROM dim_date")
    assert (first, last) == (date(2026, 1, 15), date(2026, 4, 5))
    assert days == store.count("dim_date")
    assert store.one("SELECT month_name FROM dim_date WHERE date_key = DATE '2026-03-10'")[0] == "март"


def test_new_organisations_are_added_once(store: Store) -> None:
    load(store, sample())
    suppliers = build_suppliers(store)
    customers = build_customers(store)
    assert suppliers.added == 2, "два ИНН поставщиков в наборе"
    assert customers.added == 2
    assert store.count("dim_supplier", "is_current") == 2


def test_second_build_finds_nothing_new(store: Store) -> None:
    load(store, sample())
    build_suppliers(store)
    again = build_suppliers(store)
    assert (again.added, again.changed) == (0, 0)
    assert again.unchanged > 0
    assert store.count("dim_supplier") == 3, "две организации, у одной две версии"


def test_rename_opens_a_second_version(store: Store) -> None:
    load(store, sample())
    build_suppliers(store)
    versions = store.query(
        "SELECT name, valid_from, valid_to, is_current FROM dim_supplier WHERE inn = '7712345678' ORDER BY valid_from"
    )
    assert [row[0] for row in versions] == ["ООО «Ромашка»", "ООО «Ромашка Плюс»"]
    assert versions[0][2] == date(2026, 4, 5), "прежняя версия закрывается днём переименования"
    assert versions[0][3] is False
    assert versions[1][2] == date(9999, 12, 31)
    assert versions[1][3] is True


def test_history_has_no_gaps_between_versions(store: Store) -> None:
    load(store, sample())
    build_suppliers(store)
    versions = store.query("SELECT valid_from, valid_to FROM dim_supplier WHERE inn = '7712345678' ORDER BY valid_from")
    assert versions[0][1] == versions[1][0], "конец прежнего интервала — начало следующего"


def test_backdated_name_does_not_rewrite_history(store: Store) -> None:
    load(store, sample())
    build_suppliers(store)
    load(store, [raw(number="К-99", signed="01.01.2026", supplier="ООО «Ромашка Старая»")], source="старьё.csv")
    report = build_suppliers(store)
    assert report.ignored == 1, "версия из прошлого не должна переписывать историю задним числом"
    assert store.count("dim_supplier", "inn = '7712345678'") == 2


def test_customer_region_change_is_a_new_version(store: Store) -> None:
    load(store, sample())
    build_customers(store)
    load(store, [raw(number="К-50", signed="10.05.2026", region="50")], source="переезд.csv")
    report = build_customers(store)
    assert report.changed == 1
    regions = store.query(
        "SELECT region_code, is_current FROM dim_customer WHERE inn = '7701000001' ORDER BY valid_from"
    )
    assert [row[0] for row in regions] == ["77", "50"]
    assert [row[1] for row in regions] == [False, True]
