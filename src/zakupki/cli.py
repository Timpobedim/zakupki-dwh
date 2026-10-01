"""Командная строка: generate, load, build, quality, marts, report, history, demo."""

from __future__ import annotations

import argparse
import io
import sys
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

from zakupki import demo as demo_module
from zakupki import facts, marts, quality, report
from zakupki.dimensions import build_customers, build_dates, build_suppliers
from zakupki.generate import Plan, write_csv
from zakupki.load import LoadError, load_csv
from zakupki.store import Store, StoreError

WAREHOUSE = "закупки.duckdb"


def main(argv: Sequence[str] | None = None) -> int:
    _utf8_console()
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (StoreError, LoadError, ValueError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2


def _utf8_console() -> None:
    """В стандартной консоли Windows нет ни «₽», ни «—»: без этого отчёт падает на первом же рубле."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper) and stream.encoding.lower() not in {"utf-8", "utf8"}:
            stream.reconfigure(encoding="utf-8", errors="replace")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zakupki", description="Хранилище закупок: слои, «звезда», качество")
    commands = parser.add_subparsers(dest="command", required=True)

    generate = commands.add_parser("generate", help="сгенерировать выгрузку для опытов")
    generate.add_argument("--out", type=Path, required=True)
    generate.add_argument("--contracts", type=int, default=400)
    generate.add_argument("--seed", type=int, default=7)
    generate.add_argument("--encoding", default="cp1251")
    generate.set_defaults(handler=_generate)

    load = commands.add_parser("load", help="загрузить выгрузку в stage")
    load.add_argument("--warehouse", type=Path, default=Path(WAREHOUSE))
    load.add_argument("--file", type=Path, required=True)
    load.add_argument("--force", action="store_true", help="загрузить, даже если такой файл уже был")
    load.set_defaults(handler=_load)

    build = commands.add_parser("build", help="собрать измерения и факт")
    build.add_argument("--warehouse", type=Path, default=Path(WAREHOUSE))
    build.add_argument("--since", type=_day, help="начало периода, ДД.ММ.ГГГГ")
    build.add_argument("--until", type=_day, help="конец периода, ДД.ММ.ГГГГ")
    build.set_defaults(handler=_build)

    check = commands.add_parser("quality", help="проверки качества")
    check.add_argument("--warehouse", type=Path, default=Path(WAREHOUSE))
    check.add_argument("--fresh-days", type=int, default=quality.FRESH_DAYS)
    check.add_argument("--strict", action="store_true", help="считать предупреждения ошибками")
    check.set_defaults(handler=_quality)

    mart = commands.add_parser("marts", help="пересобрать витрины")
    mart.add_argument("--warehouse", type=Path, default=Path(WAREHOUSE))
    mart.set_defaults(handler=_marts)

    show = commands.add_parser("report", help="отчёт по хранилищу")
    show.add_argument("--warehouse", type=Path, default=Path(WAREHOUSE))
    show.set_defaults(handler=_report)

    history = commands.add_parser("history", help="история организации по ИНН")
    history.add_argument("--warehouse", type=Path, default=Path(WAREHOUSE))
    history.add_argument("--inn", required=True)
    history.set_defaults(handler=_history)

    show_demo = commands.add_parser("demo", help="показать весь путь: выгрузка, загрузка, звезда, качество")
    show_demo.add_argument("--root", type=Path)
    show_demo.add_argument("--contracts", type=int, default=400)
    show_demo.set_defaults(handler=_demo)
    return parser


def _generate(args: argparse.Namespace) -> int:
    lines = write_csv(args.out, Plan(contracts=args.contracts, seed=args.seed), encoding=args.encoding)
    print(f"Выгрузка записана: {args.out} ({lines} строк, кодировка {args.encoding}).")
    return 0


def _load(args: argparse.Namespace) -> int:
    with Store(args.warehouse) as store:
        result = load_csv(store, args.file, force=args.force)
        print(result.line)
        for reason, number in result.reasons:
            print(f"  {reason} — {number}")
    return 0


def _build(args: argparse.Namespace) -> int:
    with Store(args.warehouse) as store:
        days = build_dates(store)
        suppliers = build_suppliers(store)
        customers = build_customers(store)
        built = facts.build(store, since=args.since, until=args.until)
        print(f"Календарь: {days} дней.")
        print(
            f"Поставщики: новых {suppliers.added}, новых версий {suppliers.changed}, "
            f"без изменений {suppliers.unchanged}, пропущено {suppliers.ignored}."
        )
        print(
            f"Заказчики: новых {customers.added}, новых версий {customers.changed}, "
            f"без изменений {customers.unchanged}, пропущено {customers.ignored}."
        )
        print(built.line)
    return 0


def _quality(args: argparse.Namespace) -> int:
    with Store(args.warehouse) as store:
        checks = quality.run(store, fresh_days=args.fresh_days)
    print(report.quality_block(checks))
    if quality.errors(checks):
        return 1
    if args.strict and quality.warnings(checks):
        return 1
    return 0


def _marts(args: argparse.Namespace) -> int:
    with Store(args.warehouse) as store:
        sizes = marts.build(store)
    print("Витрины пересобраны: " + ", ".join(f"{name} — {rows} строк" for name, rows in sizes.items()) + ".")
    return 0


def _report(args: argparse.Namespace) -> int:
    with Store(args.warehouse) as store:
        if not store.count("fact_contract"):
            print("Факт пуст: сначала «zakupki load», затем «zakupki build».")
            return 0
        checks = quality.run(store)
        print(report.summary(store, checks))
        print()
        print("Помесячно:")
        print(report.months_table(store))
    return 0


def _history(args: argparse.Namespace) -> int:
    with Store(args.warehouse) as store:
        print(report.history_table(store, args.inn))
    return 0


def _demo(args: argparse.Namespace) -> int:
    result = demo_module.run(root=args.root, contracts=args.contracts)
    print(result.text)
    return 1 if quality.errors(result.checks) else 0


def _day(text: str) -> date:
    try:
        return datetime.strptime(text, "%d.%m.%Y").date()  # noqa: DTZ007 — календарная дата, не момент
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"дата в формате ДД.ММ.ГГГГ, получено «{text}»") from exc


if __name__ == "__main__":
    raise SystemExit(main())
