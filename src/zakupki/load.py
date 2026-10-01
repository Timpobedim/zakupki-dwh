"""Загрузка выгрузки в слой stage: кодировка, разбор, повторная загрузка того же файла.

Повторная загрузка — обычное дело: файл прислали дважды, задание перезапустили, выгрузку прислали
исправленную. Поэтому у каждой загрузки считается отпечаток содержимого: тот же файл второй раз
не грузится вовсе, а исправленный приходит новой партией и перекрывает прежнюю версию контракта.

Загрузка инкрементальная: никакого `DROP TABLE` и полной перезаливки на каждый запуск.
"""

from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from zakupki.rows import Contract, Problem, parse
from zakupki.store import Store

ENCODINGS: Final = ("utf-8-sig", "cp1251")
"""Выгрузки приходят и в UTF-8, и в кодировке Windows: пробуем обе, а не падаем на первой же букве «я»."""


class LoadError(RuntimeError):
    """Файл выгрузки не прочитать."""


@dataclass(frozen=True, slots=True)
class LoadResult:
    batch_id: int
    source: str
    total: int
    accepted: int
    rejected: int
    duplicates: int
    skipped: bool = False
    reasons: tuple[tuple[str, int], ...] = ()

    @property
    def line(self) -> str:
        if self.skipped:
            return f"Файл «{self.source}» уже загружен партией №{self.batch_id} — пропускаю."
        parts = [
            f"Партия №{self.batch_id}: строк {self.total}",
            f"принято {self.accepted}",
            f"отброшено {self.rejected}",
        ]
        if self.duplicates:
            parts.append(f"повторов в файле {self.duplicates}")
        return ", ".join(parts) + "."


def read_text(path: Path) -> str:
    """Читает файл, пробуя кодировки по очереди."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise LoadError(f"Не удалось прочитать {path}: {exc}") from exc
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise LoadError(f"Файл {path.name} не читается ни в одной из кодировок: {', '.join(ENCODINGS)}")


def load_csv(store: Store, path: Path, *, force: bool = False) -> LoadResult:
    """Загружает файл выгрузки в stage."""
    text = read_text(path)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    rows = [dict(row) for row in reader]
    return load_rows(store, rows, source=path.name, content_hash=digest, force=force)


def load_rows(
    store: Store,
    rows: Sequence[Mapping[str, str]],
    *,
    source: str,
    content_hash: str,
    force: bool = False,
) -> LoadResult:
    """Разбирает строки и кладёт их в stage одной партией."""
    known = store.batch_by_hash(content_hash)
    if known is not None and not force:
        return LoadResult(
            batch_id=known.batch_id,
            source=source,
            total=known.rows_total,
            accepted=known.rows_accepted,
            rejected=known.rows_rejected,
            duplicates=0,
            skipped=True,
        )

    accepted: dict[str, Contract] = {}
    problems: list[Problem] = []
    duplicates = 0
    for number, raw in enumerate(rows, start=2):  # строка 1 — заголовок
        contract, problem = parse(raw, number)
        if problem is not None:
            problems.append(problem)
            continue
        if contract is None:
            continue
        if contract.registry_number in accepted:
            duplicates += 1
            continue
        accepted[contract.registry_number] = contract

    batch_id = store.next_id("seq_batch")
    store.executemany(
        "INSERT INTO stage_contract VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [contract.row(batch_id) for contract in accepted.values()],
    )
    store.executemany(
        "INSERT INTO stage_rejected VALUES (?,?,?,?,?)",
        [problem.row(batch_id) for problem in problems],
    )
    store.record_batch(
        batch_id=batch_id,
        source=source,
        content_hash=content_hash,
        total=len(rows),
        accepted=len(accepted),
        rejected=len(problems),
    )
    return LoadResult(
        batch_id=batch_id,
        source=source,
        total=len(rows),
        accepted=len(accepted),
        rejected=len(problems),
        duplicates=duplicates,
        reasons=_reasons(problems),
    )


def _reasons(problems: Sequence[Problem]) -> tuple[tuple[str, int], ...]:
    counts: dict[str, int] = {}
    for problem in problems:
        key = f"{problem.field}: {problem.reason}"
        counts[key] = counts.get(key, 0) + 1
    return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
