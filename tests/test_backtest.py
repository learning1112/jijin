from __future__ import annotations

import unittest

import pandas as pd

from fund_backtest.backtest import run_backtest_from_series
from fund_backtest.eastmoney import FundSeries, parse_pingzhongdata


class ParsePingzhongdataTests(unittest.TestCase):
    def test_parse_net_worth_trend(self) -> None:
        raw = (
            'var Data_netWorthTrend = ['
            '{"x":1609459200000,"y":1.0},'
            '{"x":1609545600000,"y":1.1}'
            "];"
        )

        series = parse_pingzhongdata(raw, code="1")

        self.assertEqual(series.code, "000001")
        self.assertEqual(series.data_type, "net_worth")
        self.assertEqual(list(series.frame["value"]), [1.0, 1.1])

    def test_parse_million_income(self) -> None:
        raw = "var Data_millionCopiesIncome = [[1609459200000,1.0],[1609545600000,2.0]];"

        series = parse_pingzhongdata(raw, code="000307")

        self.assertEqual(series.data_type, "million_income")
        self.assertEqual(list(series.frame["value"]), [1.0, 2.0])


class BacktestTests(unittest.TestCase):
    def test_net_worth_curve(self) -> None:
        frame = pd.DataFrame(
            {"value": [1.0, 1.1, 1.21]},
            index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        )
        series = FundSeries(code="000001", data_type="net_worth", frame=frame)

        result = run_backtest_from_series({"000001": series}, {"000001": 1.0})

        self.assertAlmostEqual(result.values["total"].iloc[-1], 12100.0)
        self.assertAlmostEqual(result.metrics["total_return"], 0.21)
        self.assertAlmostEqual(result.metrics["max_drawdown"], 0.0)

    def test_million_income_compounds(self) -> None:
        frame = pd.DataFrame(
            {"value": [10.0, 10.0]},
            index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
        )
        series = FundSeries(code="000307", data_type="million_income", frame=frame)

        result = run_backtest_from_series({"000307": series}, {"000307": 1.0})

        self.assertAlmostEqual(result.values["total"].iloc[-1], 10020.01, places=2)


if __name__ == "__main__":
    unittest.main()
