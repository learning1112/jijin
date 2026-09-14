"""固定 all_weather4 权重，用候选债基替换 000139 (权重 0.50)，逐一回测汇总。

权重固定: 000216=0.25, 000834=0.20, [候选债基]=0.50, 004243=0.05
候选筛选: 债券型-* 基金，且净值数据早于 start (满足 >10 年)，仍在交易。
复用 sweep_weights 的快速路径函数。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))  # 让 import sweep_weights 可用
sys.path.insert(0, str(PROJECT_ROOT))

from sweep_weights import (  # noqa: E402
    metrics_from_fast,
    precompute_relative,
    precompute_schedule,
    simulate_fast,
)
from fund_backtest.cache import CsvFundCache  # noqa: E402

DEFAULT_PORTFOLIO = PROJECT_ROOT / "data" / "portfolios" / "all_weather4.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "replace_bond_all_weather4.csv"
FUND_LIST_CANDIDATES = [
    PROJECT_ROOT / "data" / "fund_codes.csv",  # 网页“数据管理”生成的目录（英文列名）
    PROJECT_ROOT / "基金列表.csv",               # 旧版手工下载的目录（中文列名）
]

METRIC_KEYS = [
    "end_value", "total_return", "annual_return", "max_drawdown",
    "volatility", "sharpe", "elapsed_days", "total_fees",
    "rebalance_count", "average_turnover", "total_contributions",
    "net_profit", "return_on_contributions",
]


def _load_bond_catalog():
    """读取基金目录，兼容 data/fund_codes.csv (code/name/fund_type) 与 基金列表.csv (中文列名)。"""
    for path in FUND_LIST_CANDIDATES:
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                fund_type = row.get("fund_type") or row.get("基金类型") or ""
                if not fund_type.startswith("债券型"):
                    continue
                code = row.get("code") or row.get("基金代码") or ""
                name = row.get("name") or row.get("基金简称") or ""
                if code:
                    yield code, fund_type, name
        return


def discover_bond_candidates(cache_dir: str, earliest: str, live_since: str):
    """返回 [(code, subtype, name, first_date, last_date)]，均为债券型且数据早于 earliest 仍存活。"""
    bond = {code: (subtype, name) for code, subtype, name in _load_bond_catalog()}

    out = []
    for code, (subtype, name) in bond.items():
        path = os.path.join(cache_dir, f"{code}.csv")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            f.readline()
            first = f.readline().strip()
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 200))
            tail = f.read().strip().splitlines()
        last = tail[-1] if tail else ""
        first_date = first.split(",")[0] if first else ""
        last_date = last.split(",")[0] if last else ""
        if first_date and first_date <= earliest and last_date >= live_since:
            out.append((code, subtype, name, first_date, last_date))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="固定权重替换债基并回测汇总")
    p.add_argument("--portfolio", type=Path, default=DEFAULT_PORTFOLIO)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--bond-weight", type=float, default=None,
                   help="债基权重，默认读 portfolio 中 000139 的权重")
    p.add_argument("--earliest", default=None,
                   help="候选债基净值首日须 <= 此日期，默认取 portfolio start")
    p.add_argument("--live-since", default="2025-01-01",
                   help="候选债基须有此日期后的数据（仍在交易）")
    args = p.parse_args(argv)

    with args.portfolio.open(encoding="utf-8") as fh:
        portfolio = json.load(fh)
    payload = portfolio["payload"]
    start = payload.get("start") or None
    end = payload.get("end") or None
    cache_dir = str(payload.get("cache_dir") or "data/fund_cache")

    funds = {str(f["code"]).strip().zfill(6): float(f["weight"]) for f in payload["funds"]}
    if "000139" not in funds:
        raise SystemExit("portfolio 不含 000139，无法确定替换目标。")
    bond_weight = args.bond_weight if args.bond_weight is not None else funds["000139"]
    # 固定其他 3 只权重，债基位置替换
    fixed_codes = [c for c in funds if c != "000139"]
    fixed_weights = [funds[c] for c in fixed_codes]

    earliest = args.earliest or (start or "2016-01-01")
    print(f"[config] 固定基金: {list(zip(fixed_codes, fixed_weights))}")
    print(f"[config] 候选债基权重: {bond_weight}")
    print(f"[config] 候选须 <= {earliest} 且 >= {args.live_since}")

    candidates = discover_bond_candidates(cache_dir, earliest, args.live_since)
    # 把原始 000139 也纳入作为基准
    baseline = None
    for i, c in enumerate(candidates):
        if c[0] == "000139":
            baseline = i
            break
    print(f"[discover] 债基候选: {len(candidates)} 只"
          + ("（含 000139 基准）" if baseline is not None else "（未含 000139，将单独追加）"))

    cache = CsvFundCache(cache_dir)

    # 预加载固定基金
    fixed_series = {}
    for c in fixed_codes:
        s = cache.load(c)
        if s is None:
            raise SystemExit(f"固定基金 {c} 未缓存，无法回测。")
        fixed_series[c] = s

    rows = []
    t0 = time.time()
    for idx, (bcode, subtype, name, fdate, ldate) in enumerate(candidates):
        bs = cache.load(bcode)
        if bs is None:
            continue
        codes = fixed_codes + [bcode]
        series_by_code = dict(fixed_series)
        series_by_code[bcode] = bs
        try:
            index, rel = precompute_relative(series_by_code, codes, start, end)
            is_contrib, is_rebal = precompute_schedule(
                index,
                contribution_amount=float(payload.get("contribution_amount") or 0.0),
                contribution_frequency=str(payload.get("contribution_frequency") or "monthly"),
                contribution_weekday=str(payload.get("contribution_weekday") or "monday"),
                rebalance_frequency=str(payload.get("rebalance_frequency") or "none"),
            )
            w_arr = np.array(fixed_weights + [bond_weight], dtype=float)
            total_arr, contrib_arr, fees_arr, turnover_arr, rebal_arr = simulate_fast(
                rel, w_arr, is_contrib, is_rebal,
                initial_cash=float(payload.get("initial_cash") or 0.0),
                fee_rate=float(payload.get("fee_rate") or 0.0),
                contribution_amount=float(payload.get("contribution_amount") or 0.0),
            )
            metrics = metrics_from_fast(index, total_arr, contrib_arr, fees_arr, turnover_arr, rebal_arr)
        except Exception as exc:  # noqa: BLE001
            print(f"  [skip] {bcode} {name}: {exc}")
            continue

        row = {
            "bond_code": bcode,
            "bond_name": name,
            "bond_type": subtype,
            "is_original": bcode == "000139",
        }
        for k in METRIC_KEYS:
            row[k] = metrics.get(k, "")
        rows.append(row)

        if (idx + 1) % 100 == 0 or idx + 1 == len(candidates):
            el = time.time() - t0
            print(f"[sweep] {idx + 1}/{len(candidates)}  速率 {el and (idx+1)/el:.1f}/s")

    rows.sort(key=lambda r: float(r.get("sharpe") or 0.0), reverse=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["bond_code", "bond_name", "bond_type", "is_original"] + METRIC_KEYS
    with args.output.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"\n[done] 已写入 {args.output}（{len(rows)} 行，按 Sharpe 倒序）")
    _print_top(rows, "整体 Top 10")
    for st in ["债券型-长债", "债券型-中短债", "债券型-混合一级", "债券型-混合二级"]:
        sub = [r for r in rows if r["bond_type"] == st]
        if sub:
            _print_top(sub, f"{st} Top 5")
    # 000139 基准位置
    for i, r in enumerate(rows):
        if r["bond_code"] == "000139":
            print(f"\n[baseline] 000139 原债基 Sharpe 排名: 第 {i+1}/{len(rows)}"
                  f"  年化 {float(r['annual_return'])*100:.2f}%"
                  f"  回撤 {float(r['max_drawdown'])*100:.2f}%"
                  f"  Sharpe {float(r['sharpe']):.3f}")
            break
    return 0


def _print_top(rows, title, n=10):
    print(f"\n{title}")
    print(f"  {'代码':<8} {'类型':<16} {'年化':>7} {'回撤':>8} {'Sharpe':>7} {'期末':>12}  名称")
    for r in rows[:n]:
        print(f"  {r['bond_code']:<8} {r['bond_type']:<16} "
              f"{float(r['annual_return'])*100:>6.2f}% "
              f"{float(r['max_drawdown'])*100:>7.2f}% "
              f"{float(r['sharpe']):>7.3f} "
              f"{float(r['end_value']):>12,.0f}  {r['bond_name'][:20]}")


if __name__ == "__main__":
    raise SystemExit(main())
