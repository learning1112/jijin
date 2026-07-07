from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from fund_backtest.cache import CsvFundCache
from fund_backtest.correlation import (
    calculate_sharpe_by_code,
    compute_correlation_index,
    load_correlation_payload,
)
from fund_backtest.eastmoney import FundSeries
from fund_backtest.purchase_status import save_purchase_status_index
from fund_backtest.screening import save_coverage_index


class CorrelationTests(unittest.TestCase):
    def test_compute_correlations_aligns_forward_fills_and_writes_unique_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = CsvFundCache(root / "cache")
            coverage_path = root / "coverage.csv"
            output_path = root / "correlations.csv"
            summary_path = root / "summary.json"
            save_coverage_index(
                pd.DataFrame(
                    [
                        _coverage_row("000001", "Fund A"),
                        _coverage_row("000002", "Fund B"),
                        _coverage_row("000003", "Fund C"),
                    ]
                ),
                coverage_path,
            )
            cache.save(
                FundSeries(
                    code="000001",
                    data_type="accumulated_net_worth",
                    frame=pd.DataFrame(
                        {"value": [1.0, 2.0, 4.0, 7.0]},
                        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]),
                    ),
                )
            )
            cache.save(
                FundSeries(
                    code="000002",
                    data_type="accumulated_net_worth",
                    frame=pd.DataFrame(
                        {"value": [10.0, 13.0, 16.0]},
                        index=pd.to_datetime(["2024-01-01", "2024-01-03", "2024-01-04"]),
                    ),
                )
            )
            cache.save(
                FundSeries(
                    code="000003",
                    data_type="accumulated_net_worth",
                    frame=pd.DataFrame(
                        {"value": [8.0, 7.0, 5.0, 2.0]},
                        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]),
                    ),
                )
            )

            summary = compute_correlation_index(
                coverage_path=coverage_path,
                cache_dir=root / "cache",
                output_path=output_path,
                summary_path=summary_path,
                as_of="2024-01-04",
            )

            rows = pd.read_csv(output_path, dtype=str)
            self.assertEqual(summary["fund_count"], 3)
            self.assertEqual(summary["pair_count"], 3)
            self.assertEqual(len(rows), 3)
            self.assertEqual(set(zip(rows["code_a"], rows["code_b"])), {("000001", "000002"), ("000001", "000003"), ("000002", "000003")})
            ab = rows.loc[(rows["code_a"] == "000001") & (rows["code_b"] == "000002")].iloc[0]
            self.assertAlmostEqual(float(ab["correlation"]), 0.866025403784, places=9)
            self.assertIn("fund_type_a", rows.columns)
            self.assertIn("fund_type_b", rows.columns)
            self.assertTrue(str(ab["fund_type_a"]))
            self.assertTrue(str(ab["fund_type_b"]))
            self.assertIn("sharpe_a", rows.columns)
            self.assertIn("sharpe_b", rows.columns)
            self.assertTrue(float(ab["sharpe_a"]) > 0)

            payload = load_correlation_payload(
                path=output_path,
                summary_path=summary_path,
                query="Fund A",
                sort="corr_asc",
                page=2,
                page_size=1,
            )
            self.assertEqual(payload["summary"]["filtered_count"], 2)
            self.assertEqual(payload["summary"]["page"], 2)
            self.assertEqual(payload["summary"]["page_size"], 1)
            self.assertEqual(payload["summary"]["total_pages"], 2)
            self.assertEqual(len(payload["items"]), 1)

            legacy_path = root / "legacy_correlations.csv"
            rows.drop(columns=["fund_type_a", "fund_type_b"]).to_csv(legacy_path, index=False, encoding="utf-8-sig")
            legacy_payload = load_correlation_payload(
                path=legacy_path,
                summary_path=summary_path,
                coverage_path=coverage_path,
                page_size=1,
            )
            self.assertTrue(legacy_payload["items"][0]["fund_type_a"])
            self.assertTrue(legacy_payload["items"][0]["fund_type_b"])

            purchase_status_path = root / "purchase_status.csv"
            save_purchase_status_index(
                pd.DataFrame(
                    [
                        _purchase_row("000001", "可购买"),
                        _purchase_row("000002", "不可购买"),
                        _purchase_row("000003", "限额"),
                    ]
                ),
                purchase_status_path,
            )
            tradable_payload = load_correlation_payload(
                path=output_path,
                summary_path=summary_path,
                coverage_path=coverage_path,
                purchase_status_path=purchase_status_path,
                purchase_availability="tradable",
                page_size=10,
            )
            self.assertEqual(
                {(item["code_a"], item["code_b"]) for item in tradable_payload["items"]},
                {("000001", "000003"), ("000002", "000003")},
            )
            self.assertTrue(all(item["availability_b"] == "限额" for item in tradable_payload["items"]))

            b_payload = load_correlation_payload(
                path=output_path,
                summary_path=summary_path,
                coverage_path=coverage_path,
                purchase_status_path=purchase_status_path,
                query_b="Fund A",
                page_size=10,
            )
            self.assertEqual({item["code_b"] for item in b_payload["items"]}, {"000001"})
            self.assertEqual({item["code_a"] for item in b_payload["items"]}, {"000002", "000003"})

    def test_focused_query_writes_only_pairs_for_the_selected_fund(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = CsvFundCache(root / "cache")
            coverage_path = root / "coverage.csv"
            output_path = root / "correlations.csv"
            summary_path = root / "summary.json"
            save_coverage_index(
                pd.DataFrame([_coverage_row("000001", "Fund A"), _coverage_row("000002", "Fund A Plus"), _coverage_row("000003", "Fund C")]),
                coverage_path,
            )
            for code, values in {
                "000001": [1.0, 2.0, 5.0],
                "000002": [1.0, 2.0, 3.0],
                "000003": [3.0, 2.0, 1.0],
            }.items():
                cache.save(
                    FundSeries(
                        code=code,
                        data_type="accumulated_net_worth",
                        frame=pd.DataFrame(
                            {"value": values},
                            index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
                        ),
                    )
                )

            summary = compute_correlation_index(
                coverage_path=coverage_path,
                cache_dir=root / "cache",
                output_path=output_path,
                summary_path=summary_path,
                as_of="2024-01-03",
                query="000001",
            )

            rows = pd.read_csv(output_path, dtype=str)
            self.assertEqual(summary["mode"], "focused")
            self.assertEqual(summary["query"], "000001")
            self.assertEqual(summary["pair_count"], 2)
            self.assertEqual(set(rows["code_a"]), {"000001"})
            self.assertEqual(set(rows["code_b"]), {"000002", "000003"})
            self.assertTrue(rows["fund_type_a"].astype(str).str.len().gt(0).all())
            self.assertTrue(rows["fund_type_b"].astype(str).str.len().gt(0).all())
            self.assertTrue(rows["sharpe_a"].astype(str).str.len().gt(0).all())

    def test_targeted_query_a_and_query_b_write_oriented_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = CsvFundCache(root / "cache")
            coverage_path = root / "coverage.csv"
            output_path = root / "correlations.csv"
            summary_path = root / "summary.json"
            save_coverage_index(
                pd.DataFrame([_coverage_row("000001", "Fund A"), _coverage_row("000002", "Fund B"), _coverage_row("000003", "Fund C")]),
                coverage_path,
            )
            for code, values in {
                "000001": [1.0, 2.0, 5.0],
                "000002": [1.0, 2.0, 3.0],
                "000003": [3.0, 2.0, 1.0],
            }.items():
                cache.save(
                    FundSeries(
                        code=code,
                        data_type="accumulated_net_worth",
                        frame=pd.DataFrame(
                            {"value": values},
                            index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
                        ),
                    )
                )

            summary = compute_correlation_index(
                coverage_path=coverage_path,
                cache_dir=root / "cache",
                output_path=output_path,
                summary_path=summary_path,
                as_of="2024-01-03",
                query_a="Fund A",
                query_b="Fund C",
            )

            rows = pd.read_csv(output_path, dtype=str)
            self.assertEqual(summary["query_a"], "Fund A")
            self.assertEqual(summary["query_b"], "Fund C")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows.iloc[0]["code_a"], "000001")
            self.assertEqual(rows.iloc[0]["code_b"], "000003")

            summary = compute_correlation_index(
                coverage_path=coverage_path,
                cache_dir=root / "cache",
                output_path=output_path,
                summary_path=summary_path,
                as_of="2024-01-03",
                query_a="Fund A",
            )

            rows = pd.read_csv(output_path, dtype=str)
            self.assertEqual(summary["query_a"], "Fund A")
            self.assertEqual(summary["query_b"], "")
            self.assertEqual(summary["pair_count"], 2)
            self.assertEqual(set(rows["code_a"]), {"000001"})
            self.assertEqual(set(rows["code_b"]), {"000002", "000003"})

    def test_calculate_sharpe_by_code_uses_daily_returns(self) -> None:
        returns = pd.DataFrame(
            {
                "000001": [0.01, 0.02, 0.03],
                "000002": [0.01, 0.01, 0.01],
            }
        )

        sharpes = calculate_sharpe_by_code(returns, periods_per_year=252)

        self.assertIsNotNone(sharpes["000001"])
        self.assertGreater(sharpes["000001"], 0)
        self.assertIsNone(sharpes["000002"])

    def test_load_correlation_payload_handles_empty_file_during_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_path = root / "correlations.csv"
            output_path.write_text("", encoding="utf-8")

            payload = load_correlation_payload(path=output_path, summary_path=root / "summary.json")

            self.assertEqual(payload["items"], [])
            self.assertIn("正在写入", payload["warning"])

    def test_compute_correlations_uses_only_accumulated_net_worth_funds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = CsvFundCache(root / "cache")
            coverage_path = root / "coverage.csv"
            save_coverage_index(
                pd.DataFrame(
                    [
                        _coverage_row("000001", "Fund A"),
                        _coverage_row("000002", "Fund B"),
                        {**_coverage_row("000003", "Fund C"), "data_type": "net_worth"},
                    ]
                ),
                coverage_path,
            )
            for code in ["000001", "000002", "000003"]:
                cache.save(
                    FundSeries(
                        code=code,
                        data_type="accumulated_net_worth" if code != "000003" else "net_worth",
                        frame=pd.DataFrame(
                            {"value": [1.0, 1.2, 1.5]},
                            index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
                        ),
                    )
                )

            summary = compute_correlation_index(
                coverage_path=coverage_path,
                cache_dir=root / "cache",
                output_path=root / "correlations.csv",
                summary_path=root / "summary.json",
                as_of="2024-01-03",
            )

            self.assertEqual(summary["fund_count"], 2)
            self.assertEqual(summary["pair_count"], 1)


def _coverage_row(code: str, name: str) -> dict[str, object]:
    return {
        "code": code,
        "name": name,
        "fund_type": "混合",
        "pinyin": name.upper(),
        "data_type": "accumulated_net_worth",
        "data_start": "2018-01-01",
        "data_end": "2024-01-04",
        "history_years": 6.0,
        "has_5y": True,
        "has_10y": False,
        "is_active": True,
        "as_of": "2024-01-04",
        "checked_at": "2024-01-04 00:00:00",
        "error": "",
    }


def _purchase_row(code: str, availability: str) -> dict[str, object]:
    status = "限大额" if availability == "限额" else "开放申购" if availability == "可购买" else "暂停申购"
    return {
        "code": code,
        "name": code,
        "fund_type": "混合",
        "purchase_status": status,
        "redeem_status": "开放赎回",
        "purchase_limit": "5000000" if availability == "限额" else "100000000000",
        "buy_status_code": "2" if availability == "限额" else "1" if availability == "可购买" else "4",
        "can_purchase": availability in {"可购买", "限额"},
        "is_limited": availability == "限额",
        "availability": availability,
        "min_purchase_text": "10元",
        "purchase_limit_text": "500万" if availability == "限额" else "无限额",
        "checked_at": "2026-07-06 10:00:00",
    }


if __name__ == "__main__":
    unittest.main()
