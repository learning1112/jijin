from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fund_backtest.webapp import (
    delete_portfolio,
    list_portfolios,
    load_portfolio,
    _portfolio_path,
    _sanitize_portfolio_name,
    save_portfolio,
)


class SanitizePortfolioNameTests(unittest.TestCase):
    def test_accepts_normal_name(self) -> None:
        self.assertEqual(_sanitize_portfolio_name("我的组合"), "我的组合")

    def test_strips_whitespace(self) -> None:
        self.assertEqual(_sanitize_portfolio_name("  组合  "), "组合")

    def test_accepts_inner_spaces(self) -> None:
        self.assertEqual(_sanitize_portfolio_name("我的 稳健 组合"), "我的 稳健 组合")

    def test_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            _sanitize_portfolio_name("")

    def test_rejects_only_whitespace(self) -> None:
        with self.assertRaises(ValueError):
            _sanitize_portfolio_name("   ")

    def test_rejects_forward_slash(self) -> None:
        with self.assertRaises(ValueError):
            _sanitize_portfolio_name("a/b")

    def test_rejects_backslash(self) -> None:
        with self.assertRaises(ValueError):
            _sanitize_portfolio_name("a\\b")

    def test_rejects_dot(self) -> None:
        with self.assertRaises(ValueError):
            _sanitize_portfolio_name(".")

    def test_rejects_double_dot(self) -> None:
        with self.assertRaises(ValueError):
            _sanitize_portfolio_name("..")

    def test_rejects_control_chars(self) -> None:
        with self.assertRaises(ValueError):
            _sanitize_portfolio_name("a\nb")

    def test_rejects_too_long(self) -> None:
        with self.assertRaises(ValueError):
            _sanitize_portfolio_name("x" * 65)

    def test_accepts_exactly_64_chars(self) -> None:
        self.assertEqual(_sanitize_portfolio_name("x" * 64), "x" * 64)


class PortfolioPathTests(unittest.TestCase):
    def test_has_json_extension(self) -> None:
        path = _portfolio_path("组合", base_dir=Path("/tmp/fake"))
        self.assertEqual(path.name, "组合.json")

    def test_uses_base_dir(self) -> None:
        path = _portfolio_path("组合", base_dir=Path("/custom/dir"))
        self.assertEqual(path.parent, Path("/custom/dir"))

    def test_rejects_traversal(self) -> None:
        with self.assertRaises(ValueError):
            _portfolio_path("../etc/passwd")


class SaveLoadDeleteRoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self.dir = Path(self._tmp)

    def tearDown(self) -> None:
        for child in self.dir.iterdir():
            child.unlink()
        self.dir.rmdir()

    def test_save_creates_file(self) -> None:
        wrapper = save_portfolio("组合A", {"funds": []}, base_dir=self.dir)
        self.assertTrue(_portfolio_path("组合A", base_dir=self.dir).exists())
        self.assertEqual(wrapper["name"], "组合A")
        self.assertTrue(wrapper["saved_at"])

    def test_payload_preserved(self) -> None:
        payload = {"funds": [{"code": "000307", "weight": 0.5}], "initial_cash": 10000}
        save_portfolio("组合A", payload, base_dir=self.dir)
        loaded = load_portfolio("组合A", base_dir=self.dir)
        self.assertEqual(loaded["payload"], payload)

    def test_load_returns_full_wrapper(self) -> None:
        save_portfolio("组合A", {"x": 1}, base_dir=self.dir)
        loaded = load_portfolio("组合A", base_dir=self.dir)
        self.assertIn("name", loaded)
        self.assertIn("saved_at", loaded)
        self.assertIn("payload", loaded)

    def test_load_missing_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_portfolio("不存在", base_dir=self.dir)

    def test_delete_removes_file(self) -> None:
        save_portfolio("组合A", {"x": 1}, base_dir=self.dir)
        delete_portfolio("组合A", base_dir=self.dir)
        self.assertFalse(_portfolio_path("组合A", base_dir=self.dir).exists())

    def test_delete_missing_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            delete_portfolio("不存在", base_dir=self.dir)

    def test_same_name_overwrites(self) -> None:
        save_portfolio("组合A", {"v": 1}, base_dir=self.dir)
        first = load_portfolio("组合A", base_dir=self.dir)
        save_portfolio("组合A", {"v": 2}, base_dir=self.dir)
        second = load_portfolio("组合A", base_dir=self.dir)
        self.assertEqual(first["payload"], {"v": 1})
        self.assertEqual(second["payload"], {"v": 2})
        files = list(self.dir.glob("*.json"))
        self.assertEqual(len(files), 1)


class ListPortfoliosTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self.dir = Path(self._tmp)

    def tearDown(self) -> None:
        for child in self.dir.iterdir():
            child.unlink()
        self.dir.rmdir()

    def test_empty_dir_returns_empty_list(self) -> None:
        self.assertEqual(list_portfolios(base_dir=self.dir), [])

    def test_nonexistent_dir_returns_empty_list(self) -> None:
        self.assertEqual(list_portfolios(base_dir=self.dir / "missing"), [])

    def test_lists_multiple_portfolios(self) -> None:
        save_portfolio("A", {"v": 1}, base_dir=self.dir)
        save_portfolio("B", {"v": 2}, base_dir=self.dir)
        names = {item["name"] for item in list_portfolios(base_dir=self.dir)}
        self.assertEqual(names, {"A", "B"})

    def test_sorted_by_saved_at_desc(self) -> None:
        save_portfolio("old", {"v": 1}, base_dir=self.dir)
        save_portfolio("new", {"v": 2}, base_dir=self.dir)
        # Manually rewrite timestamps to control ordering deterministically.
        old_path = _portfolio_path("old", base_dir=self.dir)
        new_path = _portfolio_path("new", base_dir=self.dir)
        old_wrapper = json.loads(old_path.read_text(encoding="utf-8"))
        new_wrapper = json.loads(new_path.read_text(encoding="utf-8"))
        old_wrapper["saved_at"] = "2020-01-01 00:00:00"
        new_wrapper["saved_at"] = "2025-12-31 23:59:59"
        old_path.write_text(json.dumps(old_wrapper, ensure_ascii=False), encoding="utf-8")
        new_path.write_text(json.dumps(new_wrapper, ensure_ascii=False), encoding="utf-8")
        items = list_portfolios(base_dir=self.dir)
        self.assertEqual([item["name"] for item in items], ["new", "old"])

    def test_skips_corrupt_json(self) -> None:
        save_portfolio("good", {"v": 1}, base_dir=self.dir)
        (self.dir / "broken.json").write_text("{not valid json", encoding="utf-8")
        items = list_portfolios(base_dir=self.dir)
        names = {item["name"] for item in items}
        self.assertEqual(names, {"good"})

    def test_list_excludes_payload(self) -> None:
        save_portfolio("A", {"secret": "value"}, base_dir=self.dir)
        items = list_portfolios(base_dir=self.dir)
        self.assertEqual(len(items), 1)
        self.assertNotIn("payload", items[0])


class EndToEndRoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self.dir = Path(self._tmp)

    def tearDown(self) -> None:
        for child in self.dir.iterdir():
            child.unlink()
        self.dir.rmdir()

    def test_full_payload_round_trip(self) -> None:
        # Mirrors the exact shape produced by the JS readPayload() function.
        payload = {
            "funds": [
                {"code": "000307", "weight": 0.25},
                {"code": "511010", "weight": 0.25},
            ],
            "initial_cash": 10000,
            "start": "2021-01-01",
            "end": None,
            "cache_dir": "data/fund_cache",
            "rebalance_frequency": "monthly",
            "fee_rate": 0.001,
            "min_history_years": 0,
            "contribution_amount": 0,
            "contribution_frequency": "monthly",
            "contribution_weekday": "monday",
            "refresh": False,
        }
        wrapper = save_portfolio("我的稳健组合", payload, base_dir=self.dir)
        self.assertEqual(wrapper["name"], "我的稳健组合")
        loaded = load_portfolio("我的稳健组合", base_dir=self.dir)
        self.assertEqual(loaded["payload"], payload)
        listed = list_portfolios(base_dir=self.dir)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["name"], "我的稳健组合")


if __name__ == "__main__":
    unittest.main()
