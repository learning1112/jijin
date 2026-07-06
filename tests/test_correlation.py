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

    def test_focused_query_writes_only_pairs_for_the_selected_fund(self) -> None:
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
                query="000001",
            )

            rows = pd.read_csv(output_path, dtype=str)
            self.assertEqual(summary["mode"], "focused")
            self.assertEqual(summary["query"], "000001")
            self.assertEqual(summary["pair_count"], 2)
            self.assertEqual(set(rows["code_a"]), {"000001"})
            self.assertEqual(set(rows["code_b"]), {"000002", "000003"})
            self.assertTrue(rows["sharpe_a"].astype(str).str.len().gt(0).all())

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


if __name__ == "__main__":
    unittest.main()
