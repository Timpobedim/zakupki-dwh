from __future__ import annotations

from pathlib import Path

import pytest
from conftest import load, raw, sample

from zakupki.generate import Plan, write_csv
from zakupki.load import LoadError, load_csv
from zakupki.store import Store


def test_rows_land_in_stage(store: Store) -> None:
    result = load(store, sample())
    assert (result.accepted, result.rejected, result.duplicates) == (4, 0, 0)
    assert store.count("stage_contract") == 4
    assert store.batches()[0].source == "выгрузка.csv"


def test_same_file_twice_changes_nothing(store: Store) -> None:
    first = load(store, sample())
    again = load(store, sample())
    assert again.skipped
    assert again.batch_id == first.batch_id
    assert store.count("stage_contract") == 4
    assert "уже загружен" in again.line


def test_force_loads_the_same_file_again(store: Store) -> None:
    load(store, sample())
    forced = load(store, sample(), force=True)
    assert not forced.skipped
    assert store.count("stage_contract") == 8, "вторая партия лежит рядом, а не поверх"
    assert store.count("(SELECT DISTINCT registry_number FROM stage_contract)") == 4


def test_corrected_file_overrides_the_previous_version(store: Store) -> None:
    load(store, sample())
    corrected = [row for row in sample() if row["Реестровый номер"] != "К-1"]
    corrected.append(raw(number="К-1", signed="15.01.2026", amount="450000,00"))
    load(store, corrected, source="выгрузка-исправленная.csv")

    latest = store.one("SELECT amount FROM stage_contract WHERE registry_number = 'К-1' ORDER BY batch_id DESC LIMIT 1")
    assert str(latest[0]) == "450000.00"


def test_duplicate_registry_number_inside_one_file(store: Store) -> None:
    result = load(store, [*sample(), raw(number="К-2", signed="20.02.2026")])
    assert result.duplicates == 1
    assert result.accepted == 4


def test_bad_rows_are_kept_with_the_reason(store: Store) -> None:
    result = load(store, [*sample(), raw(number="К-9", supplier_inn=""), raw(number="К-10", amount="—")])
    assert result.rejected == 2
    assert store.count("stage_rejected") == 2
    assert result.reasons[0][1] == 1
    fields = {row[0] for row in store.query("SELECT field FROM stage_rejected")}
    assert fields == {"ИНН поставщика", "Цена контракта"}


def test_windows_encoding_is_read(tmp_path: Path, store: Store) -> None:
    path = tmp_path / "выгрузка.csv"
    write_csv(path, Plan(contracts=20, seed=3), encoding="cp1251")
    result = load_csv(store, path)
    assert result.accepted > 0
    names = {row[0] for row in store.query("SELECT supplier_name FROM stage_contract")}
    assert any("«" in name for name in names), "кавычки-ёлочки должны пережить перекодировку"


def test_utf8_file_is_read_too(tmp_path: Path, store: Store) -> None:
    path = tmp_path / "выгрузка-utf8.csv"
    write_csv(path, Plan(contracts=15, seed=4), encoding="utf-8")
    assert load_csv(store, path).accepted > 0


def test_missing_file_is_explained(tmp_path: Path, store: Store) -> None:
    with pytest.raises(LoadError, match="Не удалось прочитать"):
        load_csv(store, tmp_path / "нет-такого.csv")
