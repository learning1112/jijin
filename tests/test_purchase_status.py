from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from fund_backtest.eastmoney import parse_purchase_status_response
from fund_backtest.purchase_status import (
    attach_purchase_status_fields,
    filter_purchase_availability,
    format_money_text,
    save_purchase_status_index,
)
from fund_backtest.webapp import search_funds_payload


class PurchaseStatusTests(unittest.TestCase):
    def test_parse_purchase_status_response_classifies_open_limited_and_closed(self) -> None:
        payload = (
            'var reData={datas:['
            '["000001","A","混合","1.0","07-06","开放申购","开放赎回","","10.0","100000000000","1.0","1","0.15%"],'
            '["000067","B","债券","0.8","07-06","限大额","开放赎回","","10.0","5000000","1.0","2","0.08%"],'
            '["000064","C","债券","1.1","07-03","暂停申购","暂停赎回","2027-05-03","100.0","100000000000","1.0","4","0.00%"]'
            '],record:"3",pages:"1",curpage:"1"}'
        )

        statuses = parse_purchase_status_response(payload)

        self.assertEqual([item.availability for item in statuses], ["可购买", "限额", "不可购买"])
        self.assertTrue(statuses[0].can_purchase)
        self.assertTrue(statuses[1].is_limited)
        self.assertFalse(statuses[2].can_purchase)

    def test_attach_purchase_status_fields_marks_catalog_rows(self) -> None:
        catalog = pd.DataFrame(
            [
                {"code": "000001", "name": "A", "fund_type": "混合", "pinyin": "A"},
                {"code": "000064", "name": "C", "fund_type": "债券", "pinyin": "C"},
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "purchase.csv"
            save_purchase_status_index(
                pd.DataFrame(
                    [
                        {
                            "code": "000001",
                            "purchase_status": "开放申购",
                            "redeem_status": "开放赎回",
                            "purchase_limit": "100000000000",
                            "buy_status_code": "1",
                            "can_purchase": True,
                            "is_limited": False,
                            "availability": "可购买",
                            "min_purchase_text": "10元",
                            "purchase_limit_text": "无限额",
                            "checked_at": "2026-07-06 10:00:00",
                        },
                        {
                            "code": "000064",
                            "purchase_status": "暂停申购",
                            "redeem_status": "暂停赎回",
                            "purchase_limit": "100000000000",
                            "buy_status_code": "4",
                            "can_purchase": False,
                            "is_limited": False,
                            "availability": "不可购买",
                            "min_purchase_text": "100元",
                            "purchase_limit_text": "无限额",
                            "checked_at": "2026-07-06 10:00:00",
                        },
                    ]
                ),
                path,
            )

            result = attach_purchase_status_fields(catalog, status_path=path)

        self.assertEqual(result.loc[result["code"] == "000001", "availability"].iloc[0], "可购买")
        self.assertEqual(result.loc[result["code"] == "000064", "purchase_status"].iloc[0], "暂停申购")

        tradable = filter_purchase_availability(result, "tradable")
        self.assertEqual([item for item in tradable["code"]], ["000001"])

    def test_search_funds_payload_includes_purchase_status(self) -> None:
        catalog = pd.DataFrame([{"code": "000067", "name": "民生加银转债优选A", "fund_type": "债券", "pinyin": "MSJY"}])

        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "purchase.csv"
            save_purchase_status_index(
                pd.DataFrame(
                    [
                        {
                            "code": "000067",
                            "purchase_status": "限大额",
                            "redeem_status": "开放赎回",
                            "purchase_limit": "5000000",
                            "buy_status_code": "2",
                            "can_purchase": True,
                            "is_limited": True,
                            "availability": "限额",
                            "min_purchase_text": "10元",
                            "purchase_limit_text": "500万",
                            "checked_at": "2026-07-06 10:00:00",
                        }
                    ]
                ),
                status_path,
            )
            with patch("fund_backtest.webapp.DEFAULT_PURCHASE_STATUS_PATH", status_path), patch(
                "fund_backtest.webapp.load_fund_catalog",
                return_value=catalog,
            ):
                payload = search_funds_payload("转债", name_only=True)
                limited_payload = search_funds_payload("转债", name_only=True, purchase_availability="limited")
                open_payload = search_funds_payload("转债", name_only=True, purchase_availability="open")

        self.assertEqual(payload["items"][0]["availability"], "限额")
        self.assertEqual(payload["items"][0]["purchase_limit_text"], "500万")
        self.assertEqual([item["code"] for item in limited_payload["items"]], ["000067"])
        self.assertEqual(open_payload["items"], [])

    def test_format_money_text(self) -> None:
        self.assertEqual(format_money_text("10"), "10元")
        self.assertEqual(format_money_text("5000000"), "500万")
        self.assertEqual(format_money_text("100000000000"), "无限额")


if __name__ == "__main__":
    unittest.main()
