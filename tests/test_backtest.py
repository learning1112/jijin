from __future__ import annotations

import json
import unittest

import pandas as pd

from fund_backtest.backtest import run_backtest_from_series
from fund_backtest.eastmoney import FundSeries, parse_pingzhongdata
from fund_backtest.report import render_html_report
from fund_backtest.webapp import APP_HTML, serialize_backtest_result


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

    def test_accumulated_net_worth_is_preferred_over_unit_net_worth(self) -> None:
        raw = (
            "var Data_millionCopiesIncome = [];"
            "var Data_netWorthTrend = [{\"x\":1609459200000,\"y\":1.0}];"
            "var Data_ACWorthTrend = [[1609459200000,1.5],[1609545600000,1.6]];"
        )

        series = parse_pingzhongdata(raw, code="000001")

        self.assertEqual(series.data_type, "accumulated_net_worth")
        self.assertEqual(list(series.frame["value"]), [1.5, 1.6])


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

        self.assertAlmostEqual(result.values["total"].iloc[-1], 10010.0, places=2)

    def test_monthly_rebalance_changes_holdings(self) -> None:
        dates = pd.to_datetime(["2024-01-31", "2024-02-01", "2024-02-02"])
        fast = FundSeries(
            code="000001",
            data_type="net_worth",
            frame=pd.DataFrame({"value": [1.0, 2.0, 4.0]}, index=dates),
        )
        flat = FundSeries(
            code="000002",
            data_type="net_worth",
            frame=pd.DataFrame({"value": [1.0, 1.0, 1.0]}, index=dates),
        )

        result = run_backtest_from_series(
            {"000001": fast, "000002": flat},
            {"000001": 0.5, "000002": 0.5},
            rebalance_frequency="monthly",
        )

        self.assertAlmostEqual(result.values["total"].iloc[-1], 22500.0)
        self.assertEqual(result.metrics["rebalance_count"], 1.0)
        self.assertAlmostEqual(result.metrics["average_turnover"], 1 / 3)
        self.assertTrue(result.values["rebalanced"].iloc[1])

    def test_fee_rate_reduces_initial_investment(self) -> None:
        frame = pd.DataFrame(
            {"value": [1.0, 1.0]},
            index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
        )
        series = FundSeries(code="000001", data_type="net_worth", frame=frame)

        result = run_backtest_from_series(
            {"000001": series},
            {"000001": 1.0},
            fee_rate=0.01,
        )

        self.assertAlmostEqual(result.values["total"].iloc[-1], 9900.0)
        self.assertAlmostEqual(result.metrics["total_fees"], 100.0)

    def test_monthly_contribution_can_start_without_initial_cash(self) -> None:
        dates = pd.to_datetime(["2024-01-31", "2024-02-01", "2024-02-02"])
        frame = pd.DataFrame({"value": [1.0, 2.0, 2.0]}, index=dates)
        series = FundSeries(code="000001", data_type="net_worth", frame=frame)

        result = run_backtest_from_series(
            {"000001": series},
            {"000001": 1.0},
            initial_cash=0.0,
            contribution_amount=1000.0,
            contribution_frequency="monthly",
        )

        self.assertEqual(list(result.values["contribution"]), [1000.0, 1000.0, 0.0])
        self.assertAlmostEqual(result.values["total"].iloc[-1], 3000.0)
        self.assertAlmostEqual(result.metrics["total_contributions"], 2000.0)
        self.assertAlmostEqual(result.metrics["return_on_contributions"], 0.5)

    def test_daily_contribution_runs_on_every_available_trading_day(self) -> None:
        dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
        frame = pd.DataFrame({"value": [1.0, 1.0, 1.0]}, index=dates)
        series = FundSeries(code="000001", data_type="net_worth", frame=frame)

        result = run_backtest_from_series(
            {"000001": series},
            {"000001": 1.0},
            initial_cash=0.0,
            contribution_amount=100.0,
            contribution_frequency="daily",
        )

        self.assertEqual(list(result.values["contribution"]), [100.0, 100.0, 100.0])
        self.assertAlmostEqual(result.metrics["total_contributions"], 300.0)

    def test_weekly_contribution_uses_selected_weekday(self) -> None:
        dates = pd.to_datetime(
            ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-08", "2024-01-10"]
        )
        frame = pd.DataFrame({"value": [1.0, 1.0, 1.0, 1.0, 1.0]}, index=dates)
        series = FundSeries(code="000001", data_type="net_worth", frame=frame)

        result = run_backtest_from_series(
            {"000001": series},
            {"000001": 1.0},
            initial_cash=0.0,
            contribution_amount=100.0,
            contribution_frequency="weekly",
            contribution_weekday="wednesday",
        )

        self.assertEqual(list(result.values["contribution"]), [0.0, 0.0, 100.0, 0.0, 100.0])
        self.assertEqual(result.metadata["contribution_weekday"], "wednesday")
        self.assertAlmostEqual(result.metrics["total_contributions"], 200.0)

    def test_weekly_contribution_before_selected_weekday_has_finite_drawdown(self) -> None:
        dates = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])
        frame = pd.DataFrame({"value": [1.0, 1.0, 1.0]}, index=dates)
        series = FundSeries(code="000001", data_type="net_worth", frame=frame)

        result = run_backtest_from_series(
            {"000001": series},
            {"000001": 1.0},
            initial_cash=0.0,
            contribution_amount=100.0,
            contribution_frequency="weekly",
            contribution_weekday="wednesday",
        )

        self.assertEqual(list(result.values["contribution"]), [0.0, 0.0, 100.0])
        self.assertFalse(result.values["drawdown"].isna().any())
        self.assertEqual(list(result.values["drawdown"]), [0.0, 0.0, 0.0])

    def test_weekly_contribution_rolls_to_next_available_day_in_same_week(self) -> None:
        dates = pd.to_datetime(["2024-01-01", "2024-01-04", "2024-01-05"])
        frame = pd.DataFrame({"value": [1.0, 1.0, 1.0]}, index=dates)
        series = FundSeries(code="000001", data_type="net_worth", frame=frame)

        result = run_backtest_from_series(
            {"000001": series},
            {"000001": 1.0},
            initial_cash=0.0,
            contribution_amount=100.0,
            contribution_frequency="weekly",
            contribution_weekday="wednesday",
        )

        self.assertEqual(list(result.values["contribution"]), [0.0, 100.0, 0.0])
        self.assertAlmostEqual(result.metrics["total_contributions"], 100.0)

    def test_annual_metrics_are_split_by_calendar_year(self) -> None:
        dates = pd.to_datetime(["2023-12-29", "2024-01-02", "2024-01-03"])
        frame = pd.DataFrame({"value": [1.0, 1.1, 1.21]}, index=dates)
        series = FundSeries(code="000001", data_type="net_worth", frame=frame)

        result = run_backtest_from_series({"000001": series}, {"000001": 1.0})

        self.assertEqual([row["year"] for row in result.annual_metrics], [2023.0, 2024.0])
        self.assertAlmostEqual(result.annual_metrics[1]["total_return"], 0.1)
        self.assertAlmostEqual(result.annual_metrics[1]["end_value"], 12100.0)


class ReportTests(unittest.TestCase):
    def test_render_html_report(self) -> None:
        frame = pd.DataFrame(
            {"value": [1.0, 1.1]},
            index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
        )
        series = FundSeries(code="000001", data_type="net_worth", frame=frame)
        result = run_backtest_from_series({"000001": series}, {"000001": 1.0})

        html = render_html_report(result, {"000001": 1.0})

        self.assertIn("Fund Backtest Report", html)
        self.assertIn("Annual Metrics", html)
        self.assertIn("Portfolio Value", html)
        self.assertIn("000001", html)


class WebAppTests(unittest.TestCase):
    def test_web_ui_contains_daily_and_weekly_contribution_controls(self) -> None:
        self.assertIn("每个交易日", APP_HTML)
        self.assertIn("contributionWeekday", APP_HTML)
        self.assertIn("定投星期", APP_HTML)

    def test_serialize_backtest_result(self) -> None:
        frame = pd.DataFrame(
            {"value": [1.0, 1.1]},
            index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
        )
        series = FundSeries(code="000001", data_type="net_worth", frame=frame)
        result = run_backtest_from_series({"000001": series}, {"000001": 1.0})

        payload = serialize_backtest_result(result, {"000001": 1.0})

        self.assertEqual(payload["period"]["start"], "2024-01-01")
        self.assertEqual(payload["final_holdings"][0]["code"], "000001")
        self.assertEqual(len(payload["series"]), 2)
        self.assertEqual(payload["annual_metrics"][0]["year"], 2024.0)

    def test_serialize_regular_contribution_metrics(self) -> None:
        frame = pd.DataFrame(
            {"value": [1.0, 1.0]},
            index=pd.to_datetime(["2024-01-01", "2024-02-01"]),
        )
        series = FundSeries(code="000001", data_type="net_worth", frame=frame)

        result = run_backtest_from_series(
            {"000001": series},
            {"000001": 1.0},
            initial_cash=0.0,
            contribution_amount=1000.0,
            contribution_frequency="monthly",
        )
        payload = serialize_backtest_result(result, {"000001": 1.0})

        self.assertAlmostEqual(payload["metrics"]["total_contributions"], 2000.0)

    def test_serialize_weekly_contribution_result_is_strict_json(self) -> None:
        dates = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])
        frame = pd.DataFrame({"value": [1.0, 1.0, 1.0]}, index=dates)
        series = FundSeries(code="000001", data_type="net_worth", frame=frame)
        result = run_backtest_from_series(
            {"000001": series},
            {"000001": 1.0},
            initial_cash=0.0,
            contribution_amount=100.0,
            contribution_frequency="weekly",
            contribution_weekday="wednesday",
        )

        payload = serialize_backtest_result(result, {"000001": 1.0})

        json.dumps(payload, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
