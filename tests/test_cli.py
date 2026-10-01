from __future__ import annotations

from pathlib import Path

import pytest

from zakupki.cli import main


@pytest.fixture
def stand(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "выгрузка.csv"
    warehouse = tmp_path / "закупки.duckdb"
    assert main(["generate", "--out", str(source), "--contracts", "120", "--seed", "11"]) == 0
    assert main(["load", "--warehouse", str(warehouse), "--file", str(source)]) == 0
    assert main(["build", "--warehouse", str(warehouse)]) == 0
    assert main(["marts", "--warehouse", str(warehouse)]) == 0
    return source, warehouse


def test_whole_path_works(stand: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    _, warehouse = stand
    capsys.readouterr()
    assert main(["report", "--warehouse", str(warehouse)]) == 0
    printed = capsys.readouterr().out
    assert "Регионы:" in printed
    assert "Поставщики:" in printed
    assert "Помесячно:" in printed


def test_second_load_of_the_same_file_is_skipped(stand: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    source, warehouse = stand
    capsys.readouterr()
    assert main(["load", "--warehouse", str(warehouse), "--file", str(source)]) == 0
    assert "уже загружен" in capsys.readouterr().out


def test_quality_prints_every_check(stand: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    _, warehouse = stand
    code = main(["quality", "--warehouse", str(warehouse)])
    printed = capsys.readouterr().out
    assert "реестровый номер уникален" in printed
    assert code in {0, 1}, "код возврата 1 — если качество не сошлось; это нормальный ответ, а не сбой"


def test_history_shows_versions(stand: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    _, warehouse = stand
    assert main(["history", "--warehouse", str(warehouse), "--inn", "7712345678"]) == 0
    printed = capsys.readouterr().out
    assert "Действует с" in printed
    assert "ООО «Ромашка»" in printed


def test_empty_warehouse_is_explained(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["report", "--warehouse", str(tmp_path / "пусто.duckdb")]) == 0
    assert "Факт пуст" in capsys.readouterr().out


def test_bad_date_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["build", "--warehouse", str(tmp_path / "пусто.duckdb"), "--since", "вчера"])


def test_demo_tells_the_whole_story(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["demo", "--root", str(tmp_path / "демо"), "--contracts", "150"])
    printed = capsys.readouterr().out
    assert code in {0, 1}
    assert "уже загружен" in printed, "повторная загрузка того же файла"
    assert "История поставщика" in printed
    assert "Качество:" in printed
