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


def _parse_fund_code_search(text: str) -> list[list[str]]:
    match = re.search(r"=\s*(\[.*\])\s*;?\s*$", text.strip(), re.DOTALL)
    if not match:
        raise ValueError("Unexpected fundcode_search.js response format.")
    return json.loads(match.group(1))


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
