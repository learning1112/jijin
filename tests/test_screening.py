from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from fund_backtest.data_management import build_coverage_index
from fund_backtest.eastmoney import FundSeries
from fund_backtest.screening import (
    coverage_row_from_series,
    coverage_row_meets_requirement,
    filter_coverage,
    load_coverage_index,
    save_coverage_index,
    validate_fund_history_requirement,
)
from fund_backtest.webapp import APP_HTML, search_funds_payload


class FakeHistoryClient:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames

    def fetch_history(self, code: str) -> FundSeries:
        code = str(code).zfill(6)
        if code not in self.frames:
            raise ValueError("boom")
        return FundSeries(code=code, data_type="net_worth", frame=self.frames[code])


def _series(code: str, dates: list[str]) -> FundSeries:
    frame = pd.DataFrame(
        {"value": [1.0] * len(dates)},
        index=pd.to_datetime(dates),
    )
    return FundSeries(code=code, data_type="net_worth", frame=frame)


class ScreeningTests(unittest.TestCase):
    def test_exactly_five_years_meets_requirement(self) -> None:
        row = coverage_row_from_series(
            {"code": "000001", "name": "A", "fund_type": "混合", "pinyin": "A"},
            _series("000001", ["2019-01-01", "2024-01-01"]),
            as_of="2024-01-01",
        )

        self.assertTrue(row["has_5y"])
        self.assertTrue(coverage_row_meets_requirement(row, min_history_years=5, as_of="2024-01-01"))

    def test_four_years_eleven_months_does_not_meet_five_year_requirement(self) -> None:
        row = coverage_row_from_series(
            {"code": "000001", "name": "A", "fund_type": "混合", "pinyin": "A"},
            _series("000001", ["2019-02-01", "2024-01-01"]),
            as_of="2024-01-01",
        )

        self.assertFalse(row["has_5y"])
        self.assertFalse(coverage_row_meets_requirement(row, min_history_years=5, as_of="2024-01-01"))

    def test_ten_years_meets_ten_year_requirement(self) -> None:
        row = coverage_row_from_series(
            {"code": "000001", "name": "A", "fund_type": "混合", "pinyin": "A"},
            _series("000001", ["2014-01-01", "2024-01-01"]),
            as_of="2024-01-01",
        )

        self.assertTrue(row["has_10y"])
        self.assertTrue(coverage_row_meets_requirement(row, min_history_years=10, as_of="2024-01-01"))

    def test_stale_latest_data_fails_by_default(self) -> None:
        row = coverage_row_from_series(
            {"code": "000001", "name": "A", "fund_type": "混合", "pinyin": "A"},
            _series("000001", ["2014-01-01", "2023-10-01"]),
            as_of="2024-01-01",
        )

        self.assertFalse(row["is_active"])
        self.assertFalse(coverage_row_meets_requirement(row, min_history_years=5, as_of="2024-01-01"))

    def test_validate_fund_history_requirement_reports_clear_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coverage_path = Path(tmp) / "coverage.csv"
            row = coverage_row_from_series(
                {"code": "000001", "name": "A", "fund_type": "混合", "pinyin": "A"},
                _series("000001", ["2020-01-01", "2024-01-01"]),
                as_of="2024-01-01",
            )
            save_coverage_index(pd.DataFrame([row]), coverage_path)

            with self.assertRaisesRegex(ValueError, "000001 数据从 2020-01-01 开始"):
                validate_fund_history_requirement(
                    ["000001"],
                    min_history_years=5,
                    as_of="2024-01-01",
                    coverage_path=coverage_path,
                )


class DataManagementTests(unittest.TestCase):
    def test_build_coverage_index_generates_resumable_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog_path = root / "catalog.csv"
            cache_dir = root / "cache"
            coverage_path = root / "coverage.csv"
            catalog_path.write_text(
                "code,name,fund_type,pinyin\n"
                "000001,Long Fund,混合,LONG\n"
                "000002,Short Fund,混合,SHORT\n"
                "000003,Bad Fund,混合,BAD\n",
                encoding="utf-8",
            )
            fake = FakeHistoryClient(
                {
                    "000001": pd.DataFrame(
                        {"value": [1.0, 1.0]},
                        index=pd.to_datetime(["2019-01-01", "2024-01-01"]),
                    ),
                    "000002": pd.DataFrame(
                        {"value": [1.0, 1.0]},
                        index=pd.to_datetime(["2021-01-01", "2024-01-01"]),
                    ),
                }
            )

            progress = []
            result = build_coverage_index(
                catalog_paths=[catalog_path],
                cache_dir=cache_dir,
                coverage_path=coverage_path,
                client=fake,  # type: ignore[arg-type]
                as_of="2024-01-01",
                progress_callback=progress.append,
            )

            self.assertEqual(result["count"], 3)
            coverage = load_coverage_index(coverage_path)
            filtered = filter_coverage(coverage, min_history_years=5, as_of="2024-01-01")
            self.assertEqual(set(coverage["code"]), {"000001", "000002", "000003"})
            self.assertEqual(list(filtered["code"]), ["000001"])
            bad_error = coverage.loc[coverage["code"] == "000003", "error"].iloc[0]
            self.assertIn("boom", bad_error)
            self.assertEqual(progress[-1]["current"], 3)


class ScreeningWebTests(unittest.TestCase):
    def test_web_ui_contains_history_filter_control(self) -> None:
        self.assertIn("历史数据年限", APP_HTML)
        self.assertIn("minHistoryYears", APP_HTML)
        self.assertIn("fund-meta", APP_HTML)
        self.assertIn("portfolio-scroll", APP_HTML)
        self.assertIn("开始：", APP_HTML)
        self.assertIn("resetValueChart", APP_HTML)
        self.assertIn("setupChartZoom", APP_HTML)
        self.assertIn("drawXAxisTicks", APP_HTML)
        self.assertIn("数据管理", APP_HTML)
        self.assertIn("生成覆盖索引", APP_HTML)
        self.assertIn("更新申购状态", APP_HTML)
        self.assertIn("purchase-badge", APP_HTML)
        self.assertIn("corrPurchaseAvailability", APP_HTML)
        self.assertIn("nameMatchPurchaseAvailability", APP_HTML)
        self.assertIn("corrQueryA", APP_HTML)
        self.assertIn("corrQueryB", APP_HTML)
        self.assertIn("B购买状态", APP_HTML)
        self.assertIn("B可买含限额", APP_HTML)
        self.assertIn("相关性分析", APP_HTML)
        self.assertIn("corrPrevPage", APP_HTML)
        self.assertIn("corrPageSize", APP_HTML)
        self.assertIn("B Sharpe", APP_HTML)
        self.assertIn("基金名称匹配", APP_HTML)
        self.assertIn("nameMatchQuery", APP_HTML)
        self.assertIn("fund_type_a", APP_HTML)
        self.assertNotIn("correlationHeatmap", APP_HTML)
        self.assertNotIn("drawCorrelationHeatmap", APP_HTML)
        self.assertNotIn("screen-funds", APP_HTML)

    def test_search_funds_filters_by_coverage_index(self) -> None:
        catalog = pd.DataFrame(
            [
                {"code": "000001", "name": "Long Fund", "fund_type": "混合", "pinyin": "LONG"},
                {"code": "000002", "name": "Short Fund", "fund_type": "混合", "pinyin": "SHORT"},
            ]
        )
        long_row = coverage_row_from_series(
            {"code": "000001", "name": "Long Fund", "fund_type": "混合", "pinyin": "LONG"},
            _series("000001", ["2019-01-01", "2024-01-01"]),
            as_of="2024-01-01",
        )
        short_row = coverage_row_from_series(
            {"code": "000002", "name": "Short Fund", "fund_type": "混合", "pinyin": "SHORT"},
            _series("000002", ["2021-01-01", "2024-01-01"]),
            as_of="2024-01-01",
        )

        with tempfile.TemporaryDirectory() as tmp:
            coverage_path = Path(tmp) / "coverage.csv"
            save_coverage_index(pd.DataFrame([long_row, short_row]), coverage_path)
            with patch("fund_backtest.webapp.DEFAULT_COVERAGE_PATH", coverage_path), patch(
                "fund_backtest.webapp.load_fund_catalog",
                return_value=catalog,
            ):
                payload = search_funds_payload(
                    "",
                    min_history_years=5,
                    as_of="2024-01-01",
                )

        self.assertEqual([item["code"] for item in payload["items"]], ["000001"])
        self.assertEqual(payload["items"][0]["data_start"], "2019-01-01")

    def test_search_funds_can_match_chinese_name_only(self) -> None:
        catalog = pd.DataFrame(
            [
                {"code": "000001", "name": "国泰纳斯达克100指数", "fund_type": "指数型", "pinyin": "GTNSDK"},
                {"code": "000002", "name": "其他基金", "fund_type": "纳斯达克主题", "pinyin": "NASIDAKE"},
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            with patch("fund_backtest.webapp.DEFAULT_COVERAGE_PATH", Path(tmp) / "missing.csv"), patch(
                "fund_backtest.webapp.load_fund_catalog",
                return_value=catalog,
            ):
                payload = search_funds_payload("纳斯达克", name_only=True, limit=10)

        self.assertEqual([item["code"] for item in payload["items"]], ["000001"])


if __name__ == "__main__":
    unittest.main()
