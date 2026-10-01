from __future__ import annotations

from datetime import date

import pytest
from conftest import load, sample

from zakupki import facts
from zakupki.store import Store


def test_fact_repeats_the_numbers_from_stage(filled: Store) -> None:
    assert filled.count("fact_contract") == 4
    amount, savings, share, single = filled.one(
        "SELECT amount, savings, savings_share, single_supplier FROM fact_contract WHERE registry_number = 'К-1'"
    )
    assert str(amount) == "900000.00"
    assert str(savings) == "100000.00"
    assert share == pytest.approx(0.1)
    assert single is False


def test_single_supplier_is_marked(filled: Store) -> None:
    single, share = filled.one("SELECT single_supplier, savings_share FROM fact_contract WHERE registry_number = 'К-3'")
    assert single is True
    assert share == pytest.approx(0.0)


def test_rebuild_changes_nothing(filled: Store) -> None:
    before = filled.one("SELECT count(*), sum(amount), sum(savings) FROM fact_contract")
    facts.build(filled)
    facts.build(filled)
    assert filled.one("SELECT count(*), sum(amount), sum(savings) FROM fact_contract") == before


def test_period_rebuild_replaces_only_its_period(filled: Store) -> None:
    result = facts.build(filled, since=date(2026, 1, 1), until=date(2026, 2, 28))
    assert result.replaced == 2, "в январе и феврале по одному контракту"
    assert filled.count("fact_contract") == 4
    assert "период" in result.line


def test_key_points_to_the_version_valid_that_day(filled: Store) -> None:
    names = dict(
        filled.query(
            """
            SELECT f.registry_number, s.name
            FROM fact_contract f JOIN dim_supplier s ON s.supplier_key = f.supplier_key
            """
        )
    )
    assert names["К-1"] == "ООО «Ромашка»", "январский контракт остаётся под прежним названием"
    assert names["К-4"] == "ООО «Ромашка Плюс»", "апрельский — под новым"


def test_fact_without_dimensions_has_empty_keys(store: Store) -> None:
    load(store, sample())
    facts.build(store)
    assert store.count("fact_contract", "supplier_key IS NULL") == 4, "проверка качества обязана это заметить"


def test_period_in_wrong_order_is_refused(filled: Store) -> None:
    with pytest.raises(ValueError, match="позже"):
        facts.build(filled, since=date(2026, 3, 1), until=date(2026, 1, 1))


def test_corrected_contract_does_not_double_the_fact(store: Store) -> None:
    load(store, sample())
    corrected = [row for row in sample() if row["Реестровый номер"] != "К-1"]
    corrected.append({**sample()[0], "Цена контракта": "450000,00"})
    load(store, corrected, source="исправление.csv")
    from conftest import build_all

    build_all(store)

    assert store.count("fact_contract") == 4
    assert str(store.one("SELECT amount FROM fact_contract WHERE registry_number = 'К-1'")[0]) == "450000.00"
