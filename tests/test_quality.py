from __future__ import annotations

from datetime import date

from conftest import TODAY, build_all, load, raw, sample

from zakupki import facts, quality
from zakupki.quality import Check
from zakupki.store import Store


def by_name(checks: list[Check]) -> dict[str, Check]:
    return {check.name: check for check in checks}


def test_clean_data_passes_every_check(filled: Store) -> None:
    checks = quality.run(filled, today=TODAY)
    assert [check.name for check in checks if not check.ok] == []
    assert quality.errors(checks) == []
    assert len(checks) == 13


def test_unknown_region_is_an_error(store: Store) -> None:
    load(store, [*sample(), raw(number="К-77", region="99")])
    build_all(store)
    check = by_name(quality.run(store, today=TODAY))["регионы есть в справочнике"]
    assert not check.ok
    assert check.level == quality.ERROR
    assert "99" in check.detail


def test_missing_dimension_keys_are_an_error(store: Store) -> None:
    load(store, sample())
    facts.build(store)
    check = by_name(quality.run(store, today=TODAY))["ключи измерений подставлены"]
    assert not check.ok
    assert "4" in check.detail


def test_amount_drift_from_stage_is_caught(filled: Store) -> None:
    filled.execute("UPDATE fact_contract SET amount = amount + 1 WHERE registry_number = 'К-1'")
    check = by_name(quality.run(filled, today=TODAY))["суммы сходятся со stage"]
    assert not check.ok
    assert check.level == quality.ERROR


def test_two_current_versions_are_caught(filled: Store) -> None:
    filled.execute("UPDATE dim_supplier SET is_current = TRUE")
    check = by_name(quality.run(filled, today=TODAY))["история поставщиков непротиворечива"]
    assert not check.ok
    assert "дублей" in check.detail


def test_overlapping_history_is_caught(filled: Store) -> None:
    filled.execute("UPDATE dim_supplier SET valid_to = DATE '9999-12-31' WHERE is_current = FALSE")
    check = by_name(quality.run(filled, today=TODAY))["история поставщиков непротиворечива"]
    assert not check.ok


def test_price_above_start_is_only_a_warning(store: Store) -> None:
    load(store, [*sample(), raw(number="К-Ц", amount="2000000,00")])
    build_all(store)
    checks = quality.run(store, today=TODAY)
    check = by_name(checks)["цена не выше начальной"]
    assert not check.ok
    assert check.level == quality.WARNING
    assert quality.errors(checks) == [], "перерасход — повод посмотреть, а не остановить загрузку"


def test_stale_data_is_a_warning(filled: Store) -> None:
    check = by_name(quality.run(filled, today=date(2027, 1, 1)))["данные свежие"]
    assert not check.ok
    assert check.level == quality.WARNING


def test_rejected_rows_are_reported(store: Store) -> None:
    load(store, [*sample(), raw(number="К-Б", supplier_inn="")])
    build_all(store)
    check = by_name(quality.run(store, today=TODAY))["выгрузка разобрана целиком"]
    assert not check.ok
    assert "1" in check.detail


def test_empty_warehouse_fails_loudly(store: Store) -> None:
    checks = quality.run(store, today=TODAY)
    assert by_name(checks)["факт не пуст"].ok is False
    assert len(quality.errors(checks)) >= 1


def test_check_line_marks_severity(filled: Store) -> None:
    checks = quality.run(filled, today=TODAY)
    assert all(check.line().startswith("+") for check in checks)
