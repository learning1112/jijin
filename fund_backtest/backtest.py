from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from typing import Literal, Mapping

import pandas as pd

from .cache import CsvFundCache
from .eastmoney import EastmoneyFundClient, FundSeries, HistoryType


RebalanceFrequency = Literal["none", "monthly", "quarterly", "yearly"]
ContributionFrequency = Literal["none", "daily", "weekly", "monthly", "quarterly", "yearly"]
ContributionWeekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday"]

CONTRIBUTION_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
}


@dataclass(frozen=True)
class BacktestResult:
    values: pd.DataFrame
    metrics: dict[str, float]
    metadata: dict[str, object] = field(default_factory=dict)
    annual_metrics: list[dict[str, float]] = field(default_factory=list)


def run_backtest(
    weights: Mapping[str, float],
    *,
    initial_cash: float = 10000.0,
    start: str | None = None,
    end: str | None = None,
    cache_dir: str = "data/fund_cache",
    refresh: bool = False,
    rebalance_frequency: RebalanceFrequency = "none",
    fee_rate: float = 0.0,
    contribution_amount: float = 0.0,
    contribution_frequency: ContributionFrequency = "monthly",
    contribution_weekday: ContributionWeekday = "monday",
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
        rebalance_frequency=rebalance_frequency,
        fee_rate=fee_rate,
        contribution_amount=contribution_amount,
        contribution_frequency=contribution_frequency,
        contribution_weekday=contribution_weekday,
    )


def run_backtest_from_series(
    series_by_code: Mapping[str, FundSeries],
    weights: Mapping[str, float],
    *,
    initial_cash: float = 10000.0,
    start: str | None = None,
    end: str | None = None,
    rebalance_frequency: RebalanceFrequency = "none",
    fee_rate: float = 0.0,
    contribution_amount: float = 0.0,
    contribution_frequency: ContributionFrequency = "monthly",
    contribution_weekday: ContributionWeekday = "monday",
) -> BacktestResult:
    normalized = normalize_weights(weights)
    if initial_cash < 0:
        raise ValueError("Initial cash cannot be negative.")
    if fee_rate < 0:
        raise ValueError("Fee rate cannot be negative.")
    if contribution_amount < 0:
        raise ValueError("Contribution amount cannot be negative.")
    if initial_cash <= 0 and not _has_active_contribution(
        contribution_amount,
        contribution_frequency,
    ):
        raise ValueError("Initial cash or active regular contributions must be positive.")
    _validate_rebalance_frequency(rebalance_frequency)
    _validate_contribution_frequency(contribution_frequency)
    _validate_contribution_weekday(contribution_weekday)

    relative_curves: dict[str, pd.Series] = {}

    for code, weight in normalized.items():
        if code not in series_by_code:
            raise KeyError(f"Missing series for fund {code}.")
        series = series_by_code[code]
        values = _slice_values(series.frame["value"], start=start, end=end)
        if values.empty:
            raise ValueError(f"Fund {code} has no data in the requested date range.")
        relative_curves[code] = _holding_curve(values, series.data_type, 1.0)

    aligned = _simulate_portfolio(
        relative_curves,
        normalized,
        initial_cash=initial_cash,
        rebalance_frequency=rebalance_frequency,
        fee_rate=fee_rate,
        contribution_amount=contribution_amount,
        contribution_frequency=contribution_frequency,
        contribution_weekday=contribution_weekday,
    )
    aligned["drawdown"] = calculate_drawdown(aligned["total"])
    metrics = calculate_metrics(aligned["total"], aligned["drawdown"], aligned["contribution"])
    metrics["total_fees"] = float(aligned["fees"].sum()) if "fees" in aligned else 0.0
    metrics["rebalance_count"] = float(aligned["rebalanced"].sum()) if "rebalanced" in aligned else 0.0
    metrics["average_turnover"] = (
        float(aligned.loc[aligned["rebalanced"], "turnover_rate"].mean())
        if "rebalanced" in aligned and bool(aligned["rebalanced"].any())
        else 0.0
    )
    metrics["total_contributions"] = float(aligned["contribution"].sum())
    metrics["net_profit"] = float(metrics["end_value"] - metrics["total_contributions"])
    metrics["return_on_contributions"] = (
        float(metrics["net_profit"] / metrics["total_contributions"])
        if metrics["total_contributions"]
        else 0.0
    )
    annual_metrics = calculate_annual_metrics(aligned)
    metadata = {
        "weights": normalized,
        "rebalance_frequency": rebalance_frequency,
        "fee_rate": fee_rate,
        "contribution_amount": contribution_amount,
        "contribution_frequency": contribution_frequency,
        "contribution_weekday": contribution_weekday,
    }
    return BacktestResult(
        values=aligned,
        metrics=metrics,
        metadata=metadata,
        annual_metrics=annual_metrics,
    )


def normalize_weights(weights: Mapping[str, float]) -> dict[str, float]:
    normalized_codes = {str(code).zfill(6): float(weight) for code, weight in weights.items()}
    total = sum(normalized_codes.values())
    if total <= 0:
        raise ValueError("Total portfolio weight must be positive.")
    return {code: weight / total for code, weight in normalized_codes.items()}


def calculate_metrics(
    total: pd.Series,
    drawdown: pd.Series,
    contribution: pd.Series | None = None,
) -> dict[str, float]:
    total = total.dropna()
    if total.empty:
        raise ValueError("Portfolio value series is empty.")

    start_value = float(total.iloc[0])
    end_value = float(total.iloc[-1])
    elapsed_days = max((total.index[-1] - total.index[0]).days, 0)
    returns = _cash_flow_adjusted_returns(total, contribution)
    if not returns.empty:
        total_return = float((1.0 + returns).prod() - 1.0)
    elif start_value > 0:
        total_return = end_value / start_value - 1.0
    else:
        total_return = 0.0
    annual_return = (
        (1.0 + total_return) ** (365.0 / elapsed_days) - 1.0
        if elapsed_days > 0 and total_return > -1.0
        else 0.0
    )

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


def calculate_annual_metrics(values: pd.DataFrame) -> list[dict[str, float]]:
    if values.empty:
        return []

    total = values["total"].dropna()
    contribution = values.get("contribution", pd.Series(0.0, index=values.index))
    annual_rows: list[dict[str, float]] = []

    for year, year_values in values.groupby(values.index.year):
        year_total = year_values["total"].dropna()
        if year_total.empty:
            continue

        year_contribution = year_values.get(
            "contribution",
            pd.Series(0.0, index=year_values.index),
        ).fillna(0.0)
        year_returns = _cash_flow_adjusted_returns(year_total, year_contribution)
        total_return = (
            float((1.0 + year_returns).prod() - 1.0)
            if not year_returns.empty
            else 0.0
        )
        elapsed_days = max((year_total.index[-1] - year_total.index[0]).days, 0)
        annual_return = (
            (1.0 + total_return) ** (365.0 / elapsed_days) - 1.0
            if elapsed_days > 0 and total_return > -1.0
            else total_return
        )
        year_drawdown = calculate_drawdown(year_total)
        volatility = float(year_returns.std() * sqrt(252)) if len(year_returns) > 1 else 0.0
        sharpe = (
            float((year_returns.mean() / year_returns.std()) * sqrt(252))
            if len(year_returns) > 1 and year_returns.std() != 0
            else 0.0
        )
        start_value = float(year_total.iloc[0])
        end_value = float(year_total.iloc[-1])
        total_contributions = float(year_contribution.sum())
        first_day_contribution = float(year_contribution.iloc[0]) if len(year_contribution) else 0.0
        additional_contributions = max(total_contributions - first_day_contribution, 0.0)
        net_profit = end_value - start_value - additional_contributions
        capital_base = start_value + additional_contributions
        rebalanced = year_values.get("rebalanced", pd.Series(False, index=year_values.index))
        turnover_rate = year_values.get("turnover_rate", pd.Series(0.0, index=year_values.index))

        annual_rows.append(
            {
                "year": float(year),
                "start_value": start_value,
                "end_value": end_value,
                "total_return": total_return,
                "annual_return": float(annual_return),
                "max_drawdown": float(year_drawdown.min()),
                "volatility": volatility,
                "sharpe": sharpe,
                "total_contributions": total_contributions,
                "net_profit": float(net_profit),
                "return_on_contributions": float(net_profit / capital_base) if capital_base else 0.0,
                "total_fees": float(year_values.get("fees", pd.Series(0.0, index=year_values.index)).sum()),
                "rebalance_count": float(rebalanced.sum()),
                "average_turnover": (
                    float(turnover_rate.loc[rebalanced.astype(bool)].mean())
                    if bool(rebalanced.astype(bool).any())
                    else 0.0
                ),
                "elapsed_days": float(elapsed_days),
            }
        )

    return annual_rows


def _cash_flow_adjusted_returns(
    total: pd.Series,
    contribution: pd.Series | None,
) -> pd.Series:
    if contribution is None:
        return total.pct_change().dropna()
    aligned_contribution = contribution.reindex(total.index).fillna(0.0)
    previous_total = total.shift(1)
    returns = (total - aligned_contribution) / previous_total - 1.0
    return returns.replace([float("inf"), float("-inf")], pd.NA).dropna()


def calculate_drawdown(total: pd.Series) -> pd.Series:
    running_max = total.cummax()
    drawdown = total / running_max.where(running_max != 0) - 1.0
    return drawdown.replace([float("inf"), float("-inf")], pd.NA).fillna(0.0).astype(float)


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


def _simulate_portfolio(
    relative_curves: Mapping[str, pd.Series],
    weights: Mapping[str, float],
    *,
    initial_cash: float,
    rebalance_frequency: RebalanceFrequency,
    fee_rate: float,
    contribution_amount: float,
    contribution_frequency: ContributionFrequency,
    contribution_weekday: ContributionWeekday,
) -> pd.DataFrame:
    index = _combined_index(relative_curves)
    relative = pd.DataFrame(index=index)
    for code, curve in relative_curves.items():
        relative[code] = curve.reindex(index).ffill().fillna(1.0)

    amounts = {code: 0.0 for code in weights}
    cumulative_contributions = 0.0
    rows: list[dict[str, object]] = []
    previous_relative: pd.Series | None = None
    previous_date: pd.Timestamp | None = None

    for date, current_relative in relative.iterrows():
        if previous_relative is None:
            for code in weights:
                amounts[code] *= float(current_relative[code])
        else:
            for code in weights:
                previous_value = float(previous_relative[code])
                current_value = float(current_relative[code])
                ratio = current_value / previous_value if previous_value else 1.0
                amounts[code] *= ratio

        contribution = 0.0
        turnover = 0.0
        turnover_rate = 0.0
        fees = 0.0
        rebalanced = False

        if previous_date is None and initial_cash > 0:
            contribution += initial_cash
        if _is_contribution_date(
            previous_date,
            date,
            contribution_frequency,
            contribution_amount,
            contribution_weekday,
        ):
            contribution += contribution_amount
        if contribution > 0:
            contribution_fee = contribution * fee_rate
            investable_contribution = max(contribution - contribution_fee, 0.0)
            for code, weight in weights.items():
                amounts[code] += investable_contribution * weight
            cumulative_contributions += contribution
            turnover += contribution
            fees += contribution_fee

        should_rebalance = (
            previous_date is not None
            and _is_rebalance_date(
                previous_date,
                date,
                rebalance_frequency,
            )
        )
        if should_rebalance:
            total_before_fee = sum(amounts.values())
            targets = {code: total_before_fee * weight for code, weight in weights.items()}
            rebalance_turnover = sum(abs(targets[code] - amounts[code]) for code in weights)
            turnover_rate = rebalance_turnover / total_before_fee if total_before_fee else 0.0
            rebalance_fees = rebalance_turnover * fee_rate
            turnover += rebalance_turnover
            fees += rebalance_fees
            total_after_fee = max(total_before_fee - rebalance_fees, 0.0)
            amounts = {code: total_after_fee * weight for code, weight in weights.items()}
            rebalanced = rebalance_frequency != "none"

        row: dict[str, object] = {code: amounts[code] for code in weights}
        row["total"] = sum(amounts.values())
        row["contribution"] = contribution
        row["cumulative_contributions"] = cumulative_contributions
        row["turnover"] = turnover
        row["turnover_rate"] = turnover_rate
        row["fees"] = fees
        row["rebalanced"] = rebalanced
        rows.append(row)
        previous_relative = current_relative
        previous_date = date

    return pd.DataFrame(rows, index=index)


def _is_rebalance_date(
    previous_date: pd.Timestamp,
    current_date: pd.Timestamp,
    frequency: RebalanceFrequency,
) -> bool:
    if frequency == "none":
        return False
    if frequency == "monthly":
        return (previous_date.year, previous_date.month) != (current_date.year, current_date.month)
    if frequency == "quarterly":
        previous_quarter = (previous_date.year, (previous_date.month - 1) // 3)
        current_quarter = (current_date.year, (current_date.month - 1) // 3)
        return previous_quarter != current_quarter
    if frequency == "yearly":
        return previous_date.year != current_date.year
    raise ValueError(f"Unsupported rebalance frequency: {frequency}")


def _is_contribution_date(
    previous_date: pd.Timestamp | None,
    current_date: pd.Timestamp,
    frequency: ContributionFrequency,
    amount: float,
    contribution_weekday: ContributionWeekday = "monday",
) -> bool:
    if amount <= 0 or frequency == "none":
        return False
    if previous_date is None:
        if frequency == "weekly":
            return _is_weekly_contribution_date(None, current_date, contribution_weekday)
        return True
    if frequency == "daily":
        return True
    if frequency == "weekly":
        return _is_weekly_contribution_date(previous_date, current_date, contribution_weekday)
    if frequency == "monthly":
        return (previous_date.year, previous_date.month) != (current_date.year, current_date.month)
    if frequency == "quarterly":
        previous_quarter = (previous_date.year, (previous_date.month - 1) // 3)
        current_quarter = (current_date.year, (current_date.month - 1) // 3)
        return previous_quarter != current_quarter
    if frequency == "yearly":
        return previous_date.year != current_date.year
    raise ValueError(f"Unsupported contribution frequency: {frequency}")


def _is_weekly_contribution_date(
    previous_date: pd.Timestamp | None,
    current_date: pd.Timestamp,
    contribution_weekday: ContributionWeekday,
) -> bool:
    target_weekday = CONTRIBUTION_WEEKDAYS[contribution_weekday]
    current_weekday = current_date.weekday()
    if previous_date is None:
        return current_weekday >= target_weekday

    previous_week = previous_date.isocalendar()
    current_week = current_date.isocalendar()
    same_week = (previous_week.year, previous_week.week) == (current_week.year, current_week.week)
    if same_week:
        return previous_date.weekday() < target_weekday <= current_weekday
    return current_weekday >= target_weekday


def _validate_rebalance_frequency(frequency: str) -> None:
    if frequency not in {"none", "monthly", "quarterly", "yearly"}:
        raise ValueError("Rebalance frequency must be one of: none, monthly, quarterly, yearly.")


def _validate_contribution_frequency(frequency: str) -> None:
    if frequency not in {"none", "daily", "weekly", "monthly", "quarterly", "yearly"}:
        raise ValueError(
            "Contribution frequency must be one of: none, daily, weekly, monthly, quarterly, yearly."
        )


def _validate_contribution_weekday(weekday: str) -> None:
    if weekday not in CONTRIBUTION_WEEKDAYS:
        raise ValueError("Contribution weekday must be one of: monday, tuesday, wednesday, thursday, friday.")


def _has_active_contribution(amount: float, frequency: str) -> bool:
    return amount > 0 and frequency != "none"


def _combined_index(curves: Mapping[str, pd.Series]) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex([])
    for curve in curves.values():
        index = index.union(pd.DatetimeIndex(curve.index))
    return index.sort_values()
