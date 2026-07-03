from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .backtest import run_backtest
from .eastmoney import EastmoneyFundClient


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "backtest":
        return _cmd_backtest(args)
    if args.command == "fund-codes":
        return _cmd_fund_codes(args)
    parser.print_help()
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fund-backtest")
    subparsers = parser.add_subparsers(dest="command")

    backtest = subparsers.add_parser("backtest", help="Run a portfolio backtest.")
    backtest.add_argument(
        "--fund",
        action="append",
        required=True,
        metavar="CODE=WEIGHT",
        help="Fund code and weight. Repeat for multiple funds.",
    )
    backtest.add_argument("--initial-cash", type=float, default=10000.0)
    backtest.add_argument("--start", help="Start date, for example 2021-01-01.")
    backtest.add_argument("--end", help="End date, for example 2025-12-31.")
    backtest.add_argument("--cache-dir", default="data/fund_cache")
    backtest.add_argument("--refresh", action="store_true", help="Ignore cache and refetch data.")
    backtest.add_argument("--output", default="output/backtest_values.csv")

    fund_codes = subparsers.add_parser("fund-codes", help="Download the public fund list.")
    fund_codes.add_argument("--output", default="data/fund_codes.csv")

    return parser


def _cmd_backtest(args: argparse.Namespace) -> int:
    weights = dict(_parse_fund_arg(item) for item in args.fund)
    result = run_backtest(
        weights,
        initial_cash=args.initial_cash,
        start=args.start,
        end=args.end,
        cache_dir=args.cache_dir,
        refresh=args.refresh,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.values.reset_index(names="date").to_csv(output_path, index=False, encoding="utf-8")

    print("Backtest complete")
    print(f"Output: {output_path}")
    for key, value in result.metrics.items():
        if key.endswith("return") or key in {"annual_return", "max_drawdown", "volatility"}:
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


def _parse_fund_arg(value: str) -> tuple[str, float]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("--fund must look like CODE=WEIGHT")
    code, weight = value.split("=", 1)
    return code.strip().zfill(6), float(weight)


if __name__ == "__main__":
    raise SystemExit(main())
