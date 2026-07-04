from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .backtest import run_backtest
from .eastmoney import EastmoneyFundClient
from .report import save_html_report
from .screening import (
    DEFAULT_COVERAGE_PATH,
    DEFAULT_MAX_STALE_DAYS,
    filter_coverage,
    load_fund_catalog,
    update_coverage_index,
    validate_fund_history_requirement,
)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "backtest":
        return _cmd_backtest(args)
    if args.command == "fund-codes":
        return _cmd_fund_codes(args)
    if args.command == "screen-funds":
        return _cmd_screen_funds(args)
    if args.command == "web":
        return _cmd_web(args)
    parser.print_help()
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fund-backtest")
    subparsers = parser.add_subparsers(dest="command")

    backtest = subparsers.add_parser("backtest", help="Run a portfolio backtest.")
    backtest.add_argument("--portfolio", help="JSON file with funds and optional defaults.")
    backtest.add_argument("--fund", action="append", metavar="CODE=WEIGHT")
    backtest.add_argument("--initial-cash", type=float, default=10000.0)
    backtest.add_argument("--start", help="Start date, for example 2021-01-01.")
    backtest.add_argument("--end", help="End date, for example 2025-12-31.")
    backtest.add_argument("--cache-dir", default="data/fund_cache")
    backtest.add_argument("--coverage", default=str(DEFAULT_COVERAGE_PATH))
    backtest.add_argument("--min-history-years", type=float, default=0.0)
    backtest.add_argument("--max-stale-days", type=int, default=DEFAULT_MAX_STALE_DAYS)
    backtest.add_argument("--refresh", action="store_true", help="Ignore cache and refetch data.")
    backtest.add_argument(
        "--rebalance-frequency",
        choices=["none", "monthly", "quarterly", "yearly"],
        default="none",
    )
    backtest.add_argument("--fee-rate", type=float, default=0.0, help="One-way trade fee rate.")
    backtest.add_argument("--contribution-amount", type=float, default=0.0)
    backtest.add_argument(
        "--contribution-frequency",
        choices=["none", "daily", "weekly", "monthly", "quarterly", "yearly"],
        default="monthly",
    )
    backtest.add_argument(
        "--contribution-weekday",
        choices=["monday", "tuesday", "wednesday", "thursday", "friday"],
        default="monday",
        help="Weekday for weekly regular contributions.",
    )
    backtest.add_argument("--output", default="output/backtest_values.csv")
    backtest.add_argument("--report", default="output/backtest_report.html")

    fund_codes = subparsers.add_parser("fund-codes", help="Download the public fund list.")
    fund_codes.add_argument("--output", default="data/fund_codes.csv")

    screen = subparsers.add_parser("screen-funds", help="Build and filter a fund history coverage index.")
    screen.add_argument("--min-history-years", type=float, default=5.0)
    screen.add_argument("--as-of", help="Reference date, for example 2026-07-04.")
    screen.add_argument("--catalog", help="Fund catalog CSV. Defaults to data/fund_codes.csv or 基金列表.csv.")
    screen.add_argument("--cache-dir", default="data/fund_cache")
    screen.add_argument("--coverage", default=str(DEFAULT_COVERAGE_PATH))
    screen.add_argument("--output", default="data/fund_universe.csv")
    screen.add_argument("--max-stale-days", type=int, default=DEFAULT_MAX_STALE_DAYS)
    screen.add_argument("--refresh", action="store_true", help="Refetch history even when coverage exists.")
    screen.add_argument("--limit", type=int, help="Only scan the first N catalog rows.")

    web = subparsers.add_parser("web", help="Start the local visual backtest UI.")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8000)
    web.add_argument("--open", action="store_true")

    return parser


def _cmd_backtest(args: argparse.Namespace) -> int:
    config = _load_portfolio_config(args.portfolio) if args.portfolio else {}
    weights = _resolve_weights(args, config)
    initial_cash = float(config.get("initial_cash", args.initial_cash))
    start = args.start if args.start is not None else config.get("start")
    end = args.end if args.end is not None else config.get("end")
    cache_dir = str(config.get("cache_dir", args.cache_dir))
    coverage = str(config.get("coverage", args.coverage))
    min_history_years = float(config.get("min_history_years", args.min_history_years))
    max_stale_days = int(config.get("max_stale_days", args.max_stale_days))
    rebalance_frequency = str(config.get("rebalance_frequency", args.rebalance_frequency))
    fee_rate = float(config.get("fee_rate", args.fee_rate))
    contribution_amount = float(config.get("contribution_amount", args.contribution_amount))
    contribution_frequency = str(config.get("contribution_frequency", args.contribution_frequency))
    contribution_weekday = str(config.get("contribution_weekday", args.contribution_weekday))
    output = str(config.get("output", args.output))
    report = str(config.get("report", args.report)) if args.report else None

    validate_fund_history_requirement(
        weights,
        min_history_years=min_history_years,
        as_of=end,
        coverage_path=coverage,
        max_stale_days=max_stale_days,
    )

    result = run_backtest(
        weights,
        initial_cash=initial_cash,
        start=start,
        end=end,
        cache_dir=cache_dir,
        rebalance_frequency=rebalance_frequency,  # type: ignore[arg-type]
        fee_rate=fee_rate,
        contribution_amount=contribution_amount,
        contribution_frequency=contribution_frequency,  # type: ignore[arg-type]
        contribution_weekday=contribution_weekday,  # type: ignore[arg-type]
        refresh=args.refresh,
    )

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.values.reset_index(names="date").to_csv(output_path, index=False, encoding="utf-8")

    report_path = None
    if report:
        report_path = save_html_report(result, weights, report)

    print("Backtest complete")
    print(f"Output: {output_path}")
    if report_path:
        print(f"Report: {report_path}")
    for key, value in result.metrics.items():
        if key.endswith("return") or key in {
            "annual_return",
            "max_drawdown",
            "volatility",
            "average_turnover",
            "return_on_contributions",
        }:
            print(f"{key}: {value:.2%}")
        else:
            print(f"{key}: {value:.4f}")
    return 0


def _cmd_fund_codes(args: argparse.Namespace) -> int:
    client = EastmoneyFundClient()
    infos = client.fetch_fund_codes()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame([info.__dict__ for info in infos])
    frame.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"Saved {len(frame)} fund records to {output_path}")
    return 0


def _cmd_screen_funds(args: argparse.Namespace) -> int:
    catalog_paths = [args.catalog] if args.catalog else None
    catalog = load_fund_catalog(catalog_paths)
    if catalog.empty:
        raise argparse.ArgumentTypeError("No fund catalog found. Run fund-codes first or provide --catalog.")

    coverage = update_coverage_index(
        catalog,
        cache_dir=args.cache_dir,
        coverage_path=args.coverage,
        client=EastmoneyFundClient(),
        as_of=args.as_of,
        max_stale_days=args.max_stale_days,
        refresh=args.refresh,
        limit=args.limit,
    )
    filtered = filter_coverage(
        coverage,
        min_history_years=args.min_history_years,
        as_of=args.as_of,
        max_stale_days=args.max_stale_days,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    filtered.to_csv(output_path, index=False, encoding="utf-8-sig")

    checked = len(coverage)
    selected = len(filtered)
    errors = int((coverage["error"].astype(str) != "").sum()) if "error" in coverage else 0
    print("Fund screening complete")
    print(f"Coverage: {args.coverage}")
    print(f"Output: {output_path}")
    print(f"Checked: {checked}")
    print(f"Selected: {selected}")
    print(f"Errors: {errors}")
    return 0


def _cmd_web(args: argparse.Namespace) -> int:
    from .webapp import run_server

    run_server(args.host, args.port, open_browser=args.open)
    return 0


def _parse_fund_arg(value: str) -> tuple[str, float]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("--fund must look like CODE=WEIGHT")
    code, weight = value.split("=", 1)
    return code.strip().zfill(6), float(weight)


def _load_portfolio_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as file:
        config = json.load(file)
    if not isinstance(config, dict):
        raise argparse.ArgumentTypeError("Portfolio config must be a JSON object.")
    return config


def _resolve_weights(args: argparse.Namespace, config: dict) -> dict[str, float]:
    if args.fund:
        return dict(_parse_fund_arg(item) for item in args.fund)

    funds = config.get("funds")
    if isinstance(funds, dict):
        return {str(code).zfill(6): float(weight) for code, weight in funds.items()}
    if isinstance(funds, list):
        return {
            str(item["code"]).zfill(6): float(item["weight"])
            for item in funds
        }

    raise argparse.ArgumentTypeError("Provide --fund CODE=WEIGHT or --portfolio with a funds object.")


if __name__ == "__main__":
    raise SystemExit(main())
