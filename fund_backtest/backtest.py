from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Mapping

import pandas as pd

from .cache import CsvFundCache
from .eastmoney import EastmoneyFundClient, FundSeries, HistoryType


@dataclass(frozen=True)
class BacktestResult:
    values: pd.DataFrame
    metrics: dict[str, float]


def run_backtest(
    weights: Mapping[str, float],
    *,
    initial_cash: float = 10000.0,
    start: str | None = None,
    end: str | None = None,
    cache_dir: str = "data/fund_cache",
    refresh: bool = False,
    client: EastmoneyFundClient | None = None,
) -> BacktestResult:
    client = client or EastmoneyFundClient()
    cache = CsvFundCache(cache_dir)
    normalized = normalize_weights(weights)
    series_by_code = {
        code: cache.get_or_fetch(code, client=client, refresh=refresh)
        for code in normalized
    }
    return run_backtest_from_series(
        series_by_code,
        normalized,
        initial_cash=initial_cash,
        start=start,
        end=end,
    )


def run_backtest_from_series(
    series_by_code: Mapping[str, FundSeries],
    weights: Mapping[str, float],
    *,
    initial_cash: float = 10000.0,
    start: str | None = None,
    end: str | None = None,
) -> BacktestResult:
    normalized = normalize_weights(weights)
    curves: dict[str, pd.Series] = {}

    for code, weight in normalized.items():
        if code not in series_by_code:
            raise KeyError(f"Missing series for fund {code}.")
        series = series_by_code[code]
        values = _slice_values(series.frame["value"], start=start, end=end)
        if values.empty:
            raise ValueError(f"Fund {code} has no data in the requested date range.")
        allocation = initial_cash * weight
        curves[code] = _holding_curve(values, series.data_type, allocation)

    index = _combined_index(curves)
    aligned = pd.DataFrame(index=index)
    for code, curve in curves.items():
        allocation = initial_cash * normalized[code]
        aligned[code] = curve.reindex(index).ffill().fillna(allocation)

    aligned["total"] = aligned[list(curves)].sum(axis=1)
    aligned["drawdown"] = aligned["total"] / aligned["total"].cummax() - 1.0
    metrics = calculate_metrics(aligned["total"], aligned["drawdown"])
    return BacktestResult(values=aligned, metrics=metrics)


def normalize_weights(weights: Mapping[str, float]) -> dict[str, float]:
    normalized_codes = {str(code).zfill(6): float(weight) for code, weight in weights.items()}
    total = sum(normalized_codes.values())
    if total <= 0:
        raise ValueError("Total portfolio weight must be positive.")
    return {code: weight / total for code, weight in normalized_codes.items()}


def calculate_metrics(total: pd.Series, drawdown: pd.Series) -> dict[str, float]:
    total = total.dropna()
    if total.empty:
        raise ValueError("Portfolio value series is empty.")

    start_value = float(total.iloc[0])
    end_value = float(total.iloc[-1])
    total_return = end_value / start_value - 1.0
    elapsed_days = max((total.index[-1] - total.index[0]).days, 0)
    annual_return = (
        (end_value / start_value) ** (365.0 / elapsed_days) - 1.0
        if elapsed_days > 0 and start_value > 0
        else 0.0
    )

    returns = total.pct_change().dropna()
    volatility = float(returns.std() * sqrt(252)) if len(returns) > 1 else 0.0
    sharpe = (
        float((returns.mean() / returns.std()) * sqrt(252))
        if len(returns) > 1 and returns.std() != 0
        else 0.0
    )

    return {
        "start_value": start_value,
        "end_value": end_value,
        "total_return": float(total_return),
        "annual_return": float(annual_return),
        "max_drawdown": float(drawdown.min()),
        "volatility": volatility,
        "sharpe": sharpe,
        "elapsed_days": float(elapsed_days),
    }


def _slice_values(values: pd.Series, start: str | None, end: str | None) -> pd.Series:
    values = values.dropna().sort_index()
    if start:
        values = values.loc[values.index >= pd.Timestamp(start)]
    if end:
        values = values.loc[values.index <= pd.Timestamp(end)]
    return values


def _holding_curve(values: pd.Series, data_type: HistoryType, allocation: float) -> pd.Series:
    values = values.astype(float)
    if data_type == "million_income":
        returns = values / 10000.0
        return allocation * (1.0 + returns).cumprod()

    first = float(values.iloc[0])
    if first <= 0:
        raise ValueError("The first net-worth value must be positive.")
    units = allocation / first
    return values * units


def _combined_index(curves: Mapping[str, pd.Series]) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex([])
    for curve in curves.values():
        index = index.union(pd.DatetimeIndex(curve.index))
    return index.sort_values()
