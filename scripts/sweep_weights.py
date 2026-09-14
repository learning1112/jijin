"""遍历 all_weather 组合的基金权重，记录各项回测指标到 CSV。

每只基金权重 >= 0.05，步长 0.05，合计 = 1.0。
为提速：基金净值只加载一次，相对曲线与定投/再平衡日程只预处理一次，
逐组合用精简的 numpy 内循环跑模拟。开始遍历前会先用参考实现
run_backtest_from_series 校验快速路径的指标一致性（误差 < 1e-9），
不一致则回退到参考实现以保证结果正确。
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from fund_backtest.backtest import (
    CONTRIBUTION_WEEKDAYS,
    _holding_curve,
    _slice_values,
    calculate_drawdown,
    calculate_metrics,
    normalize_weights,
    run_backtest_from_series,
)
from fund_backtest.cache import CsvFundCache
from fund_backtest.eastmoney import EastmoneyFundClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PORTFOLIO = PROJECT_ROOT / "data" / "portfolios" / "all_weather.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "sweep_all_weather.csv"

_METRIC_KEYS = [
    "end_value",
    "total_return",
    "annual_return",
    "max_drawdown",
    "volatility",
    "sharpe",
    "elapsed_days",
    "total_fees",
    "rebalance_count",
    "average_turnover",
    "total_contributions",
    "net_profit",
    "return_on_contributions",
]


def load_series(codes: list[str], cache_dir: str) -> dict:
    cache = CsvFundCache(cache_dir)
    client = EastmoneyFundClient()
    return {c: cache.get_or_fetch(c, client=client, refresh=False) for c in codes}


def precompute_relative(series_by_code: dict, codes: list[str], start, end):
    """返回 (date_index, rel_array[n_days, n_funds])，与权重无关。"""
    relative_curves = {}
    for code in codes:
        series = series_by_code[code]
        values = _slice_values(series.frame["value"], start=start, end=end)
        if values.empty:
            raise ValueError(f"基金 {code} 在 {start}..{end} 区间无数据。")
        relative_curves[code] = _holding_curve(values, series.data_type, 1.0)

    index = pd.DatetimeIndex([])
    for code in codes:
        index = index.union(pd.DatetimeIndex(relative_curves[code].index))
    index = index.sort_values()

    rel = np.empty((len(index), len(codes)), dtype=float)
    for j, code in enumerate(codes):
        reindexed = relative_curves[code].reindex(index).ffill().fillna(1.0)
        rel[:, j] = reindexed.to_numpy(dtype=float)
    return index, rel


def precompute_schedule(
    index: pd.DatetimeIndex,
    contribution_amount: float,
    contribution_frequency: str,
    contribution_weekday: str,
    rebalance_frequency: str,
):
    """预处理每日是否定投日 / 是否再平衡日，镜像 backtest.py 的判定逻辑。"""
    n = len(index)
    is_contrib = np.zeros(n, dtype=bool)
    is_rebal = np.zeros(n, dtype=bool)
    target_wd = CONTRIBUTION_WEEKDAYS[contribution_weekday]
    contrib_active = contribution_amount > 0 and contribution_frequency != "none"
    weekdays = np.array([d.weekday() for d in index], dtype=int)
    iso = [(d.isocalendar().year, d.isocalendar().week, d.weekday()) for d in index]
    years = index.year.to_numpy()
    months = index.month.to_numpy()

    for i in range(n):
        if contrib_active:
            if i == 0:
                if contribution_frequency == "weekly":
                    is_contrib[i] = weekdays[i] >= target_wd
                else:
                    is_contrib[i] = True
            else:
                if contribution_frequency == "daily":
                    is_contrib[i] = True
                elif contribution_frequency == "weekly":
                    py, pw, _ = iso[i - 1]
                    cy, cw, _ = iso[i]
                    same_week = (py, pw) == (cy, cw)
                    if same_week:
                        is_contrib[i] = weekdays[i - 1] < target_wd <= weekdays[i]
                    else:
                        is_contrib[i] = weekdays[i] >= target_wd
                elif contribution_frequency == "monthly":
                    is_contrib[i] = (years[i - 1], months[i - 1]) != (years[i], months[i])
                elif contribution_frequency == "quarterly":
                    pq = (years[i - 1], (months[i - 1] - 1) // 3)
                    cq = (years[i], (months[i] - 1) // 3)
                    is_contrib[i] = pq != cq
                elif contribution_frequency == "yearly":
                    is_contrib[i] = years[i - 1] != years[i]

        if i > 0 and rebalance_frequency != "none":
            if rebalance_frequency == "monthly":
                is_rebal[i] = (years[i - 1], months[i - 1]) != (years[i], months[i])
            elif rebalance_frequency == "quarterly":
                pq = (years[i - 1], (months[i - 1] - 1) // 3)
                cq = (years[i], (months[i] - 1) // 3)
                is_rebal[i] = pq != cq
            elif rebalance_frequency == "yearly":
                is_rebal[i] = years[i - 1] != years[i]

    return is_contrib, is_rebal


def simulate_fast(
    rel: np.ndarray,
    weights: np.ndarray,
    is_contrib: np.ndarray,
    is_rebal: np.ndarray,
    *,
    initial_cash: float,
    fee_rate: float,
    contribution_amount: float,
):
    """精简模拟，逐日更新各基金持仓金额。逻辑与 _simulate_portfolio 一致。"""
    n, nfunds = rel.shape
    amounts = np.zeros(nfunds, dtype=float)
    total_arr = np.zeros(n, dtype=float)
    contrib_arr = np.zeros(n, dtype=float)
    fees_arr = np.zeros(n, dtype=float)
    turnover_rate_arr = np.zeros(n, dtype=float)
    rebalanced_arr = np.zeros(n, dtype=bool)

    for i in range(n):
        if i == 0:
            amounts = amounts * rel[0]
        else:
            prev = rel[i - 1]
            cur = rel[i]
            ratio = np.divide(cur, prev, out=np.ones(nfunds), where=prev != 0)
            amounts = amounts * ratio

        contribution = 0.0
        if i == 0 and initial_cash > 0:
            contribution += initial_cash
        if is_contrib[i]:
            contribution += contribution_amount

        if contribution > 0:
            fee = contribution * fee_rate
            investable = max(contribution - fee, 0.0)
            amounts = amounts + investable * weights
            fees_arr[i] += fee

        if is_rebal[i]:
            total_before = float(amounts.sum())
            targets = total_before * weights
            rebal_turnover = float(np.abs(targets - amounts).sum())
            turnover_rate_arr[i] = rebal_turnover / total_before if total_before else 0.0
            rebal_fees = rebal_turnover * fee_rate
            total_after = max(total_before - rebal_fees, 0.0)
            amounts = total_after * weights
            fees_arr[i] += rebal_fees
            rebalanced_arr[i] = True

        total_arr[i] = float(amounts.sum())
        contrib_arr[i] = contribution

    return total_arr, contrib_arr, fees_arr, turnover_rate_arr, rebalanced_arr


def metrics_from_fast(index, total_arr, contrib_arr, fees_arr, turnover_rate_arr, rebalanced_arr):
    total_s = pd.Series(total_arr, index=index)
    drawdown = calculate_drawdown(total_s)
    metrics = calculate_metrics(total_s, drawdown, pd.Series(contrib_arr, index=index))
    metrics["total_fees"] = float(fees_arr.sum())
    metrics["rebalance_count"] = float(rebalanced_arr.sum())
    metrics["average_turnover"] = (
        float(turnover_rate_arr[rebalanced_arr].mean()) if rebalanced_arr.any() else 0.0
    )
    metrics["total_contributions"] = float(contrib_arr.sum())
    metrics["net_profit"] = float(metrics["end_value"] - metrics["total_contributions"])
    metrics["return_on_contributions"] = (
        float(metrics["net_profit"] / metrics["total_contributions"])
        if metrics["total_contributions"]
        else 0.0
    )
    return metrics


def generate_weight_combos(n_funds: int, step: float = 0.05, min_weight: float = 0.05):
    """生成 n_funds 只基金、步长 step、最小 min_weight、合计 1.0 的所有权重组合。"""
    total_units = round(1.0 / step)
    min_units = round(min_weight / step)
    deficit = total_units - n_funds * min_units
    if deficit < 0:
        raise ValueError("最小权重之和超过 1.0，无可行组合。")

    def compositions(total: int, parts: int):
        if parts == 1:
            yield (total,)
            return
        for k in range(total + 1):
            for rest in compositions(total - k, parts - 1):
                yield (k,) + rest

    for extra in compositions(deficit, n_funds):
        yield [(min_units + e) * step for e in extra]


def _close(a: float, b: float, tol: float) -> bool:
    if a == b:
        return True
    return abs(a - b) <= tol * max(1.0, abs(b))


def validate_fast_path(series_by_code, codes, rel, index, is_contrib, is_rebal, params, tol=1e-9):
    """用几个权重样本对比快速路径与参考实现的指标。"""
    samples = [
        {codes[j]: w for j, w in enumerate(wlist)}
        for wlist in [
            [0.15, 0.25, 0.05, 0.30, 0.15, 0.05],  # 原始 all_weather 权重
            [0.05, 0.05, 0.05, 0.05, 0.05, 0.75],  # 极端集中
            [0.20, 0.20, 0.20, 0.20, 0.10, 0.10],  # 较均匀
        ]
    ]
    for weights in samples:
        ref = run_backtest_from_series(series_by_code, weights, **params)
        normalized = normalize_weights(weights)
        w_arr = np.array([normalized[c] for c in codes], dtype=float)
        total_arr, contrib_arr, fees_arr, turnover_rate_arr, rebalanced_arr = simulate_fast(
            rel, w_arr, is_contrib, is_rebal,
            initial_cash=params["initial_cash"],
            fee_rate=params["fee_rate"],
            contribution_amount=params["contribution_amount"],
        )
        fast = metrics_from_fast(index, total_arr, contrib_arr, fees_arr, turnover_rate_arr, rebalanced_arr)
        for key in _METRIC_KEYS:
            if key not in ref.metrics:
                continue
            if not _close(float(fast.get(key, 0.0)), float(ref.metrics[key]), tol):
                raise AssertionError(
                    f"快速路径校验失败 {key}: fast={fast.get(key)} ref={ref.metrics[key]} "
                    f"weights={weights}"
                )
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="遍历 all_weather 组合权重并记录指标")
    parser.add_argument("--portfolio", type=Path, default=DEFAULT_PORTFOLIO)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--step", type=float, default=0.05)
    parser.add_argument("--min-weight", type=float, default=0.05)
    parser.add_argument("--no-validate", action="store_true", help="跳过快速路径校验")
    parser.add_argument("--limit", type=int, default=0, help="仅跑前 N 个组合（调试用），0=全部")
    args = parser.parse_args(argv)

    # load(...) 的真实实现（修正上方占位函数名冲突）
    with args.portfolio.open(encoding="utf-8") as fh:
        portfolio = json.load(fh)
    payload = portfolio["payload"]
    codes = [str(f["code"]).strip().zfill(6) for f in payload["funds"]]
    if len(set(codes)) != len(codes):
        raise SystemExit(f"基金代码存在重复：{codes}")

    cache_dir = str(payload.get("cache_dir") or "data/fund_cache")
    series_by_code = load_series(codes, cache_dir)

    start = payload.get("start") or None
    end = payload.get("end") or None
    index, rel = precompute_relative(series_by_code, codes, start, end)

    is_contrib, is_rebal = precompute_schedule(
        index,
        contribution_amount=float(payload.get("contribution_amount") or 0.0),
        contribution_frequency=str(payload.get("contribution_frequency") or "monthly"),
        contribution_weekday=str(payload.get("contribution_weekday") or "monday"),
        rebalance_frequency=str(payload.get("rebalance_frequency") or "none"),
    )

    params = dict(
        initial_cash=float(payload.get("initial_cash") or 0.0),
        start=start,
        end=end,
        rebalance_frequency=str(payload.get("rebalance_frequency") or "none"),
        fee_rate=float(payload.get("fee_rate") or 0.0),
        contribution_amount=float(payload.get("contribution_amount") or 0.0),
        contribution_frequency=str(payload.get("contribution_frequency") or "monthly"),
        contribution_weekday=str(payload.get("contribution_weekday") or "monday"),
    )

    use_fast = True
    if not args.no_validate:
        try:
            validate_fast_path(series_by_code, codes, rel, index, is_contrib, is_rebal, params)
            print("[validate] 快速路径指标与参考实现一致，启用快速路径。")
        except AssertionError as exc:
            print(f"[validate] 校验失败，回退到参考实现：{exc}")
            use_fast = False
    else:
        print("[validate] 已跳过。")

    combos = list(generate_weight_combos(len(codes), args.step, args.min_weight))
    total = len(combos)
    if args.limit > 0:
        combos = combos[: args.limit]
        total = len(combos)
    print(f"[sweep] {len(codes)} 只基金，共 {total} 个权重组合。")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    weight_cols = [f"w_{c}" for c in codes]
    fieldnames = ["index"] + weight_cols + _METRIC_KEYS

    rows: list[dict] = []
    tmp_path = args.output.with_suffix(args.output.suffix + ".tmp")
    t0 = time.time()
    with tmp_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for idx, wlist in enumerate(combos):
            if use_fast:
                normalized = normalize_weights({codes[j]: wlist[j] for j in range(len(codes))})
                w_arr = np.array([normalized[c] for c in codes], dtype=float)
                total_arr, contrib_arr, fees_arr, turnover_rate_arr, rebalanced_arr = simulate_fast(
                    rel, w_arr, is_contrib, is_rebal,
                    initial_cash=params["initial_cash"],
                    fee_rate=params["fee_rate"],
                    contribution_amount=params["contribution_amount"],
                )
                metrics = metrics_from_fast(
                    index, total_arr, contrib_arr, fees_arr, turnover_rate_arr, rebalanced_arr
                )
            else:
                weights = {codes[j]: wlist[j] for j in range(len(codes))}
                result = run_backtest_from_series(series_by_code, weights, **params)
                metrics = dict(result.metrics)

            row = {"index": idx}
            for j, c in enumerate(codes):
                row[f"w_{c}"] = f"{wlist[j]:.2f}"
            for key in _METRIC_KEYS:
                row[key] = metrics.get(key, "")
            writer.writerow(row)
            rows.append(row)

            if (idx + 1) % 1000 == 0 or idx + 1 == total:
                elapsed = time.time() - t0
                rate = (idx + 1) / elapsed
                eta = (total - idx - 1) / rate if rate else 0
                print(f"[sweep] {idx + 1}/{total}  速率 {rate:.1f}/s  剩余 ~{eta:.0f}s")

    # 按 Sharpe 倒序写最终文件
    rows.sort(key=lambda r: float(r.get("sharpe") or 0.0), reverse=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    tmp_path.unlink(missing_ok=True)

    print(f"\n[done] 已写入 {args.output}（{len(rows)} 行，按 Sharpe 倒序）")
    print("\nTop 10（按 Sharpe）：")
    print(f"  {'权重':<40} {'年化':>8} {'回撤':>8} {'Sharpe':>8} {'期末资产':>14}")
    for r in rows[:10]:
        w = " ".join(f"{r[f'w_{c}']}" for c in codes)
        print(
            f"  {w:<40} "
            f"{float(r['annual_return'])*100:>7.2f}% "
            f"{float(r['max_drawdown'])*100:>7.2f}% "
            f"{float(r['sharpe']):>8.3f} "
            f"{float(r['end_value']):>14,.0f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
