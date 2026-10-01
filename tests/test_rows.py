from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from conftest import raw

from zakupki import rows


def test_money_survives_real_formatting() -> None:
    assert rows.money("1 234 567,89") == Decimal("1234567.89")
    assert rows.money("1 234 567,89") == Decimal("1234567.89")
    assert rows.money("900000.00") == Decimal("900000.00")
    assert rows.money(" 12 000,5 ") == Decimal("12000.50")
    assert rows.money("1 000,00 руб.") == Decimal("1000.00")


@pytest.mark.parametrize("text", ["", "—", "-", "нет", "много", "12,3,4"])
def test_money_refuses_nonsense(text: str) -> None:
    with pytest.raises(rows.FieldError):
        rows.money(text)


def test_negative_amount_is_refused() -> None:
    with pytest.raises(rows.FieldError, match="отрицательная"):
        rows.money("-5000,00")


def test_three_date_formats_are_understood() -> None:
    assert rows.day("15.02.2026") == date(2026, 2, 15)
    assert rows.day("2026-02-15") == date(2026, 2, 15)
    assert rows.day("15/02/2026") == date(2026, 2, 15)


@pytest.mark.parametrize("text", ["", "вчера", "15.13.2026", "2026"])
def test_broken_dates_are_refused(text: str) -> None:
    with pytest.raises(rows.FieldError):
        rows.day(text)


def test_inn_is_ten_or_twelve_digits() -> None:
    assert rows.inn("7712345678") == "7712345678"
    assert rows.inn(" 770123456789 ") == "770123456789"
    with pytest.raises(rows.FieldError, match="10 или 12"):
        rows.inn("771")
    with pytest.raises(rows.FieldError, match="10 или 12"):
        rows.inn("77123456АБ")
    with pytest.raises(rows.FieldError, match="пусто"):
        rows.inn("")


def test_missing_bids_mean_zero() -> None:
    assert rows.count("") == 0
    assert rows.count("4") == 4
    with pytest.raises(rows.FieldError, match="целое число"):
        rows.count("много")


def test_good_row_becomes_a_contract() -> None:
    contract, problem = rows.parse(raw(), 2)
    assert problem is None
    assert contract is not None
    assert contract.registry_number == "К-1"
    assert contract.signed_on == date(2026, 2, 15)
    assert contract.amount == Decimal("900000.00")
    assert contract.start_price == Decimal("1000000.00")
    assert contract.bids == 3


@pytest.mark.parametrize(
    ("changes", "field", "reason"),
    [
        ({"supplier_inn": ""}, "ИНН поставщика", "пусто"),
        ({"amount": "—"}, "Цена контракта", "пусто"),
        ({"signed": "позавчера"}, "Дата контракта", "непонятная дата"),
        ({"customer_inn": "77"}, "ИНН заказчика", "10 или 12"),
        ({"number": "  "}, "Реестровый номер", "пусто"),
    ],
)
def test_bad_row_names_the_field(changes: dict[str, str], field: str, reason: str) -> None:
    contract, problem = rows.parse(raw(**changes), 7)
    assert contract is None
    assert problem is not None
    assert problem.field == field
    assert reason in problem.reason
    assert problem.row_number == 7


def test_problem_keeps_the_original_line() -> None:
    _, problem = rows.parse(raw(amount="—"), 3)
    assert problem is not None
    assert "К-1" in problem.raw
