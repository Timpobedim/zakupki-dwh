"""Схема хранилища: три слоя, справочники и ключи.

Слои разделены намеренно. `stage` — выгрузка как пришла, вместе с журналом того, что не удалось
разобрать. `core` — «звезда»: измерения с суррогатными ключами и историей, факт с внешними ключами.
`mart` — витрины, которые читает аналитик.

«Звезда» описана в DDL, а не только на картинке: ключи, типы дат и чисел — настоящие, без плоских
выгрузок с датами во FLOAT.
"""

from __future__ import annotations

from datetime import date
from typing import Final

FAR_FUTURE: Final = date(9999, 12, 31)
"""Конец действия текущей версии строки измерения: так интервалы не имеют дырок."""

REGIONS: Final = {
    "77": "Москва",
    "78": "Санкт-Петербург",
    "50": "Московская область",
    "52": "Нижегородская область",
    "16": "Республика Татарстан",
    "66": "Свердловская область",
    "24": "Красноярский край",
    "23": "Краснодарский край",
    "54": "Новосибирская область",
    "72": "Тюменская область",
}

OKPD: Final = {
    "62.01": "Разработка программного обеспечения",
    "62.02": "Консультирование в области ИТ",
    "26.20": "Компьютеры и периферийное оборудование",
    "43.21": "Электромонтажные работы",
    "41.20": "Строительство зданий",
    "86.10": "Деятельность больничных организаций",
    "58.11": "Издание книг",
    "49.39": "Перевозки пассажиров",
    "35.30": "Пар и горячая вода",
    "81.29": "Уборка и санитарная обработка",
}

METHODS: Final = (
    "электронный аукцион",
    "открытый конкурс",
    "запрос котировок",
    "единственный поставщик",
)

DDL: Final = (
    "CREATE SEQUENCE IF NOT EXISTS seq_batch START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_customer START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_supplier START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_contract START 1",
    """
    CREATE TABLE IF NOT EXISTS load_batch (
        batch_id BIGINT PRIMARY KEY,
        source VARCHAR,
        content_hash VARCHAR,
        loaded_at TIMESTAMP,
        rows_total INTEGER,
        rows_accepted INTEGER,
        rows_rejected INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stage_contract (
        batch_id BIGINT,
        registry_number VARCHAR,
        signed_on DATE,
        customer_inn VARCHAR,
        customer_name VARCHAR,
        region_code VARCHAR,
        supplier_inn VARCHAR,
        supplier_name VARCHAR,
        okpd_code VARCHAR,
        subject VARCHAR,
        start_price DECIMAL(18,2),
        amount DECIMAL(18,2),
        bids INTEGER,
        method VARCHAR,
        PRIMARY KEY (batch_id, registry_number)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stage_rejected (
        batch_id BIGINT,
        row_number INTEGER,
        field VARCHAR,
        reason VARCHAR,
        raw VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dim_date (
        date_key DATE PRIMARY KEY,
        year INTEGER,
        quarter INTEGER,
        month INTEGER,
        month_name VARCHAR,
        day_of_month INTEGER
    )
    """,
    "CREATE TABLE IF NOT EXISTS dim_region (region_code VARCHAR PRIMARY KEY, region_name VARCHAR)",
    "CREATE TABLE IF NOT EXISTS dim_okpd (okpd_code VARCHAR PRIMARY KEY, okpd_name VARCHAR)",
    """
    CREATE TABLE IF NOT EXISTS dim_customer (
        customer_key BIGINT PRIMARY KEY,
        inn VARCHAR,
        name VARCHAR,
        region_code VARCHAR,
        valid_from DATE,
        valid_to DATE,
        is_current BOOLEAN
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dim_supplier (
        supplier_key BIGINT PRIMARY KEY,
        inn VARCHAR,
        name VARCHAR,
        valid_from DATE,
        valid_to DATE,
        is_current BOOLEAN
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fact_contract (
        contract_key BIGINT PRIMARY KEY,
        registry_number VARCHAR,
        signed_on DATE,
        customer_key BIGINT,
        supplier_key BIGINT,
        region_code VARCHAR,
        okpd_code VARCHAR,
        method VARCHAR,
        start_price DECIMAL(18,2),
        amount DECIMAL(18,2),
        savings DECIMAL(18,2),
        savings_share DOUBLE,
        bids INTEGER,
        single_supplier BOOLEAN,
        batch_id BIGINT
    )
    """,
)

LATEST_STAGE: Final = """
    SELECT * FROM (
        SELECT *, row_number() OVER (PARTITION BY registry_number ORDER BY batch_id DESC) AS rn
        FROM stage_contract
    ) WHERE rn = 1
"""
"""Последняя версия каждого контракта: исправленная выгрузка перекрывает прежнюю, а не дублирует её."""
