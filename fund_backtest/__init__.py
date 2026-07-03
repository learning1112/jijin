"""Small fund backtesting toolkit backed by Eastmoney/Tiantian Fund data."""

from .backtest import BacktestResult, run_backtest, run_backtest_from_series
from .eastmoney import EastmoneyFundClient, FundSeries

__all__ = [
    "BacktestResult",
    "EastmoneyFundClient",
    "FundSeries",
    "run_backtest",
    "run_backtest_from_series",
]
