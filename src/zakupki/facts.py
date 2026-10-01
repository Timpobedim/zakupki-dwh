"""Факт: перезапись периода целиком и подбор той версии измерения, что действовала на дату контракта.

Приём называется «перезапись раздела»: вместо того чтобы решать, какие строки обновились, а какие нет,
факт за период удаляется и собирается из stage заново. Результат не зависит от числа запусков — можно
перезапускать задание сколько угодно раз, суммы не удвоятся.

Без `DROP TABLE` и полной перезаливки хранилища при каждом запуске.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from zakupki.schema import LATEST_STAGE
from zakupki.store import Store

SINGLE_SUPPLIER = "единственный поставщик"


@dataclass(frozen=True, slots=True)
class BuildResult:
    rows: int
    replaced: int
    since: date | None
    until: date | None

    @property
    def line(self) -> str:
        period = "за всё время"
        if self.since and self.until:
            period = f"за период {self.since:%d.%m.%Y} — {self.until:%d.%m.%Y}"
        return f"Факт собран {period}: строк {self.rows}, перезаписано {self.replaced}."


def build(store: Store, *, since: date | None = None, until: date | None = None) -> BuildResult:
    """Собирает факт из stage. Без периода — целиком, с периодом — только его."""
    if since and until and since > until:
        raise ValueError("Начало периода позже его конца")
    window = "WHERE s.signed_on BETWEEN ? AND ?" if since and until else ""
    parameters: list[object] = [since, until] if since and until else []

    replaced = _existing(store, since, until)
    if since and until:
        store.execute("DELETE FROM fact_contract WHERE signed_on BETWEEN ? AND ?", [since, until])
    else:
        store.execute("DELETE FROM fact_contract")

    base = int(store.one("SELECT coalesce(max(contract_key), 0) FROM fact_contract")[0])
    store.execute(
        f"""
        INSERT INTO fact_contract
        SELECT CAST(? AS BIGINT) + row_number() OVER (ORDER BY s.signed_on, s.registry_number),
               s.registry_number,
               s.signed_on,
               c.customer_key,
               p.supplier_key,
               s.region_code,
               s.okpd_code,
               s.method,
               s.start_price,
               s.amount,
               s.start_price - s.amount,
               CASE WHEN s.start_price > 0
                    THEN CAST((s.start_price - s.amount) AS DOUBLE) / CAST(s.start_price AS DOUBLE)
                    ELSE 0.0 END,
               s.bids,
               s.method = '{SINGLE_SUPPLIER}',
               s.batch_id
        FROM ({LATEST_STAGE}) s
        LEFT JOIN dim_customer c
               ON c.inn = s.customer_inn AND s.signed_on >= c.valid_from AND s.signed_on < c.valid_to
        LEFT JOIN dim_supplier p
               ON p.inn = s.supplier_inn AND s.signed_on >= p.valid_from AND s.signed_on < p.valid_to
        {window}
        """,  # noqa: S608 — всё, что подставляется, объявлено в этом пакете; значения идут параметрами
        [base, *parameters],
    )
    rows = store.count("fact_contract")
    return BuildResult(rows=rows, replaced=replaced, since=since, until=until)


def _existing(store: Store, since: date | None, until: date | None) -> int:
    if since and until:
        return int(store.one("SELECT count(*) FROM fact_contract WHERE signed_on BETWEEN ? AND ?", [since, until])[0])
    return store.count("fact_contract")
