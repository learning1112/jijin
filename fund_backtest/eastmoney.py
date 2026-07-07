from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Literal

import pandas as pd
import requests


HistoryType = Literal["net_worth", "million_income", "accumulated_net_worth"]


DEFAULT_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Pragma": "no-cache",
    "Referer": "https://fund.eastmoney.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
}


@dataclass(frozen=True)
class FundInfo:
    code: str
    abbreviation: str
    name: str
    fund_type: str
    pinyin: str


@dataclass(frozen=True)
class FundSeries:
    code: str
    data_type: HistoryType
    frame: pd.DataFrame


@dataclass(frozen=True)
class FundPurchaseStatus:
    code: str
    name: str
    fund_type: str
    latest_value: str
    latest_date: str
    purchase_status: str
    redeem_status: str
    next_open_date: str
    min_purchase_amount: str
    purchase_limit: str
    buy_status_code: str
    fee_rate: str
    can_purchase: bool
    is_limited: bool
    availability: str


class EastmoneyFundClient:
    """Client for public Eastmoney/Tiantian Fund JavaScript endpoints."""

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: float = 15.0,
        pause_seconds: float = 0.2,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout
        self.pause_seconds = pause_seconds

    def fetch_fund_codes(self) -> list[FundInfo]:
        url = "https://fund.eastmoney.com/js/fundcode_search.js"
        response = self.session.get(url, headers=DEFAULT_HEADERS, timeout=self.timeout)
        response.raise_for_status()
        rows = _parse_fund_code_search(response.text)
        return [
            FundInfo(
                code=str(row[0]).zfill(6),
                abbreviation=str(row[1]),
                name=str(row[2]),
                fund_type=str(row[3]),
                pinyin=str(row[4]),
            )
            for row in rows
        ]

    def fetch_history(self, code: str) -> FundSeries:
        code = str(code).zfill(6)
        url = f"https://fund.eastmoney.com/pingzhongdata/{code}.js"
        params = {"v": str(int(time.time() * 1000))}
        response = self.session.get(
            url,
            params=params,
            headers={**DEFAULT_HEADERS, "Referer": f"https://fund.eastmoney.com/{code}.html"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        if self.pause_seconds:
            time.sleep(self.pause_seconds)
        return parse_pingzhongdata(response.text, code=code)

    def fetch_purchase_statuses(self, page_size: int = 30000) -> list[FundPurchaseStatus]:
        url = "https://fund.eastmoney.com/Data/Fund_JJJZ_Data.aspx"
        params = {
            "t": "8",
            "page": f"1,{page_size}",
            "js": "reData",
            "sort": "fcode,asc",
        }
        response = self.session.get(url, params=params, headers=DEFAULT_HEADERS, timeout=self.timeout)
        response.raise_for_status()
        if self.pause_seconds:
            time.sleep(self.pause_seconds)
        return parse_purchase_status_response(response.text)


def parse_pingzhongdata(text: str, code: str = "") -> FundSeries:
    """Parse a pingzhongdata JavaScript response into a normalized series."""

    code = str(code).zfill(6) if code else ""

    rows = _try_load_js_assignment(text, "Data_millionCopiesIncome")
    if rows:
        frame = _frame_from_pairs(rows)
        return FundSeries(code=code, data_type="million_income", frame=frame)

    rows = _try_load_js_assignment(text, "Data_ACWorthTrend")
    if rows:
        frame = _frame_from_pairs(rows)
        return FundSeries(code=code, data_type="accumulated_net_worth", frame=frame)

    rows = _try_load_js_assignment(text, "Data_netWorthTrend")
    if rows:
        frame = _frame_from_records(rows, value_key="y")
        return FundSeries(code=code, data_type="net_worth", frame=frame)

    raise ValueError("No supported net-worth series found in pingzhongdata response.")


def parse_purchase_status_response(text: str) -> list[FundPurchaseStatus]:
    rows = _extract_purchase_status_rows(text)
    return [_purchase_status_from_row(row) for row in rows]


def _parse_fund_code_search(text: str) -> list[list[str]]:
    match = re.search(r"=\s*(\[.*\])\s*;?\s*$", text.strip(), re.DOTALL)
    if not match:
        raise ValueError("Unexpected fundcode_search.js response format.")
    return json.loads(match.group(1))


def _extract_purchase_status_rows(text: str) -> list[list[str]]:
    match = re.search(r"datas\s*:\s*(\[.*?\])\s*,\s*record\s*:", text.strip(), re.DOTALL)
    if not match:
        raise ValueError("Unexpected purchase status response format.")
    return json.loads(match.group(1))


def _purchase_status_from_row(row: list) -> FundPurchaseStatus:
    values = ["" if value is None else str(value).strip() for value in row]
    values += [""] * max(0, 13 - len(values))
    code = values[0].zfill(6)
    purchase_status = values[5]
    purchase_limit = values[9]
    buy_status_code = values[11]
    can_purchase = _can_purchase(purchase_status, buy_status_code)
    is_limited = can_purchase and _is_purchase_limited(purchase_status, purchase_limit)
    availability = "限额" if is_limited else "可购买" if can_purchase else "不可购买"
    return FundPurchaseStatus(
        code=code,
        name=values[1],
        fund_type=values[2],
        latest_value=values[3],
        latest_date=values[4],
        purchase_status=purchase_status,
        redeem_status=values[6],
        next_open_date=values[7],
        min_purchase_amount=values[8],
        purchase_limit=purchase_limit,
        buy_status_code=buy_status_code,
        fee_rate=values[12],
        can_purchase=can_purchase,
        is_limited=is_limited,
        availability=availability,
    )


def _can_purchase(purchase_status: str, buy_status_code: str) -> bool:
    if buy_status_code not in {"1", "2", "3", "8", "9"}:
        return False
    blocked_words = ["暂停", "停止", "封闭", "终止", "失败", "不可", "不开放"]
    return not any(word in purchase_status for word in blocked_words)


def _is_purchase_limited(purchase_status: str, purchase_limit: str) -> bool:
    if "限" in purchase_status:
        return True
    try:
        return 0 <= float(purchase_limit) < 800000000
    except (TypeError, ValueError):
        return False


def _load_js_assignment(text: str, variable: str):
    raw = _extract_js_assignment(text, variable)
    cleaned = raw.replace("undefined", "null")
    return json.loads(cleaned)


def _try_load_js_assignment(text: str, variable: str):
    try:
        return _load_js_assignment(text, variable)
    except ValueError:
        return None


def _extract_js_assignment(text: str, variable: str) -> str:
    pattern = rf"(?:var\s+)?{re.escape(variable)}\s*=\s*(.*?);"
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        raise ValueError(f"{variable} was not found in response.")
    return match.group(1).strip()


def _frame_from_records(rows: list[dict], value_key: str) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "timestamp": [row.get("x") for row in rows],
            "value": [row.get(value_key) for row in rows],
        }
    )
    return _normalize_frame(frame)


def _frame_from_pairs(rows: list[list[float]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["timestamp", "value"])
    return _normalize_frame(frame)


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame["timestamp"] = pd.to_numeric(frame["timestamp"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "value"])
    frame["date"] = (
        pd.to_datetime(frame["timestamp"].astype("int64"), unit="ms", utc=True)
        .dt.tz_convert("Asia/Shanghai")
        .dt.tz_localize(None)
        .dt.normalize()
    )
    frame = frame[["date", "value"]].drop_duplicates("date").sort_values("date")
    return frame.set_index("date")
