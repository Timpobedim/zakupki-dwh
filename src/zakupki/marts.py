"""Витрины: три готовых ответа на вопросы, которые задают чаще всего.

Витрина материализуется таблицей, а не остаётся представлением: аналитик читает готовые числа, а
пересчёт происходит один раз после сборки факта.
"""

from __future__ import annotations

from typing import Final

from zakupki.store import Store

MARTS: Final = {
    "mart_region": """
        CREATE OR REPLACE TABLE mart_region AS
        SELECT r.region_code,
               r.region_name,
               count(*) AS contracts,
               sum(f.amount) AS amount,
               sum(f.savings) AS savings,
               avg(f.savings_share) AS savings_share,
               avg(CASE WHEN f.single_supplier THEN 1.0 ELSE 0.0 END) AS single_share
        FROM fact_contract f
        JOIN dim_region r ON r.region_code = f.region_code
        GROUP BY 1, 2
        ORDER BY amount DESC
    """,
    # Факт ссылается на ту версию поставщика, что действовала на дату контракта, а в витрине нужно
    # текущее название: иначе один и тот же ИНН выглядел бы двумя разными компаниями.
    "mart_supplier": """
        CREATE OR REPLACE TABLE mart_supplier AS
        SELECT s.inn,
               any_value(current_version.name) AS supplier_name,
               count(*) AS contracts,
               count(DISTINCT f.customer_key) AS customers,
               sum(f.amount) AS amount,
               avg(f.savings_share) AS savings_share
        FROM fact_contract f
        JOIN dim_supplier s ON s.supplier_key = f.supplier_key
        JOIN dim_supplier current_version ON current_version.inn = s.inn AND current_version.is_current
        GROUP BY 1
        ORDER BY amount DESC
    """,
    "mart_month": """
        CREATE OR REPLACE TABLE mart_month AS
        SELECT d.year,
               d.month,
               max(d.month_name) AS month_name,
               count(*) AS contracts,
               sum(f.amount) AS amount,
               avg(f.savings_share) AS savings_share,
               sum(CASE WHEN f.single_supplier THEN 1 ELSE 0 END) AS single_contracts
        FROM fact_contract f
        JOIN dim_date d ON d.date_key = f.signed_on
        GROUP BY 1, 2
        ORDER BY 1, 2
    """,
}


def build(store: Store) -> dict[str, int]:
    """Пересобирает все витрины и возвращает число строк в каждой."""
    sizes: dict[str, int] = {}
    for name, statement in MARTS.items():
        store.execute(statement)
        sizes[name] = store.count(name)
    return sizes
