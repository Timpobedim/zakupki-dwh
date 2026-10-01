"""Подключение к хранилищу и общие мелочи: создание схемы, запросы, журнал загрузок."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from zakupki.schema import DDL, OKPD, REGIONS


class StoreError(RuntimeError):
    """Хранилище недоступно или запрос не выполнился."""


@dataclass(frozen=True, slots=True)
class Batch:
    batch_id: int
    source: str
    content_hash: str
    loaded_at: datetime
    rows_total: int
    rows_accepted: int
    rows_rejected: int


class Store:
    """Один файл DuckDB со всеми слоями."""

    def __init__(self, path: Path | str = ":memory:") -> None:
        try:
            self.connection = duckdb.connect(str(path))
        except duckdb.Error as exc:
            raise StoreError(f"Не удалось открыть хранилище {path}: {exc}") from exc
        for statement in DDL:
            self.execute(statement)
        self._fill_references()

    def _fill_references(self) -> None:
        """Справочники регионов и ОКПД2 короткие и меняются редко — они едут вместе с кодом."""
        self.executemany(
            "INSERT INTO dim_region VALUES (?, ?) "
            "ON CONFLICT (region_code) DO UPDATE SET region_name = excluded.region_name",
            [[code, name] for code, name in REGIONS.items()],
        )
        self.executemany(
            "INSERT INTO dim_okpd VALUES (?, ?) ON CONFLICT (okpd_code) DO UPDATE SET okpd_name = excluded.okpd_name",
            [[code, name] for code, name in OKPD.items()],
        )

    # ── журнал загрузок ─────────────────────────────────────────────────────────────────────────

    def next_id(self, sequence: str) -> int:
        return int(self.query(f"SELECT nextval('{sequence}')")[0][0])

    def batch_by_hash(self, content_hash: str) -> Batch | None:
        rows = self.query("SELECT * FROM load_batch WHERE content_hash = ? ORDER BY batch_id DESC", [content_hash])
        return _batch(rows[0]) if rows else None

    def record_batch(
        self, *, batch_id: int, source: str, content_hash: str, total: int, accepted: int, rejected: int
    ) -> Batch:
        self.execute(
            "INSERT INTO load_batch VALUES (?,?,?,?,?,?,?)",
            [batch_id, source, content_hash, datetime.now(UTC).replace(tzinfo=None), total, accepted, rejected],
        )
        return _batch(self.query("SELECT * FROM load_batch WHERE batch_id = ?", [batch_id])[0])

    def batches(self, limit: int = 20) -> list[Batch]:
        rows = self.query("SELECT * FROM load_batch ORDER BY batch_id DESC LIMIT ?", [limit])
        rows.reverse()
        return [_batch(row) for row in rows]

    # ── низкий уровень ──────────────────────────────────────────────────────────────────────────

    def execute(self, sql: str, parameters: Sequence[object] | None = None) -> None:
        try:
            self.connection.execute(sql, list(parameters) if parameters else None)
        except duckdb.Error as exc:
            raise StoreError(f"Запрос не выполнился: {exc}") from exc

    def executemany(self, sql: str, rows: Sequence[Sequence[object]]) -> None:
        if not rows:
            return
        try:
            self.connection.executemany(sql, [list(row) for row in rows])
        except duckdb.Error as exc:
            raise StoreError(f"Запрос не выполнился: {exc}") from exc

    def query(self, sql: str, parameters: Sequence[object] | None = None) -> list[tuple[Any, ...]]:
        try:
            return list(self.connection.execute(sql, list(parameters) if parameters else None).fetchall())
        except duckdb.Error as exc:
            raise StoreError(f"Запрос не выполнился: {exc}") from exc

    def one(self, sql: str, parameters: Sequence[object] | None = None) -> tuple[Any, ...]:
        rows = self.query(sql, parameters)
        if not rows:
            raise StoreError("Запрос не вернул ни одной строки")
        return rows[0]

    def count(self, table: str, where: str = "") -> int:
        condition = f" WHERE {where}" if where else ""
        return int(self.one(f"SELECT count(*) FROM {table}{condition}")[0])  # noqa: S608 — имена таблиц свои

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _batch(row: Sequence[Any]) -> Batch:
    return Batch(
        batch_id=int(row[0]),
        source=str(row[1]),
        content_hash=str(row[2]),
        loaded_at=row[3],
        rows_total=int(row[4]),
        rows_accepted=int(row[5]),
        rows_rejected=int(row[6]),
    )
