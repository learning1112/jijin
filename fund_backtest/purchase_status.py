from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from .eastmoney import EastmoneyFundClient


DEFAULT_PURCHASE_STATUS_PATH = Path("data/fund_purchase_status.csv")
TRADABLE_AVAILABILITIES = {"可购买", "限额"}
PURCHASE_AVAILABILITY_LABELS = {
    "open": "可购买",
    "limited": "限额",
    "closed": "不可购买",
    "unknown": "未知",
}
PURCHASE_STATUS_COLUMNS = [
    "code",
    "name",
    "fund_type",
    "latest_value",
    "latest_date",
    "purchase_status",
    "redeem_status",
    "next_open_date",
    "min_purchase_amount",
    "purchase_limit",
    "buy_status_code",
    "fee_rate",
    "can_purchase",
    "is_limited",
    "availability",
    "min_purchase_text",
    "purchase_limit_text",
    "checked_at",
]


def refresh_purchase_status_index(
    *,
    output_path: str | Path = DEFAULT_PURCHASE_STATUS_PATH,
    client: EastmoneyFundClient | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> pd.DataFrame:
    if progress_callback:
        progress_callback({"message": "正在获取申购状态", "current": 0, "total": 1})
    client = client or EastmoneyFundClient()
    statuses = client.fetch_purchase_statuses()
    checked_at = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    frame = pd.DataFrame([status.__dict__ for status in statuses])
    if frame.empty:
        frame = pd.DataFrame(columns=PURCHASE_STATUS_COLUMNS)
    frame["min_purchase_text"] = frame["min_purchase_amount"].map(format_money_text)
    frame["purchase_limit_text"] = frame["purchase_limit"].map(format_money_text)
    frame["checked_at"] = checked_at
    frame = _ensure_purchase_status_columns(frame)
    save_purchase_status_index(frame, output_path)
    if progress_callback:
        progress_callback({"message": "申购状态已更新", "current": 1, "total": 1, "count": len(frame)})
    return frame


def load_purchase_status_index(path: str | Path = DEFAULT_PURCHASE_STATUS_PATH) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=PURCHASE_STATUS_COLUMNS)
    frame = pd.read_csv(path, dtype=str).fillna("")
    return _ensure_purchase_status_columns(frame)


def save_purchase_status_index(frame: pd.DataFrame, path: str | Path = DEFAULT_PURCHASE_STATUS_PATH) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    output = _ensure_purchase_status_columns(frame)
    output.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def attach_purchase_status_fields(
    catalog: pd.DataFrame,
    *,
    status_path: str | Path = DEFAULT_PURCHASE_STATUS_PATH,
) -> pd.DataFrame:
    output = catalog.copy()
    for column in PURCHASE_STATUS_COLUMNS:
        if column not in output.columns:
            output[column] = ""
    if output.empty:
        return output

    status_path = Path(status_path)
    if not status_path.exists():
        output["availability"] = "未知"
        return output

    status = load_purchase_status_index(status_path)
    if status.empty:
        output["availability"] = "未知"
        return output

    fields = [
        "code",
        "purchase_status",
        "redeem_status",
        "next_open_date",
        "min_purchase_amount",
        "purchase_limit",
        "buy_status_code",
        "fee_rate",
        "can_purchase",
        "is_limited",
        "availability",
        "min_purchase_text",
        "purchase_limit_text",
        "checked_at",
    ]
    output = output.drop(columns=[column for column in fields if column != "code"], errors="ignore")
    output = output.merge(status[fields].drop_duplicates("code"), on="code", how="left").fillna("")
    output.loc[output["availability"].astype(str).str.strip().eq(""), "availability"] = "未知"
    return output


def filter_purchase_availability(
    frame: pd.DataFrame,
    availability_filter: str,
    *,
    column: str = "availability",
) -> pd.DataFrame:
    mode = str(availability_filter or "").strip()
    if mode in {"", "all"} or column not in frame.columns:
        return frame
    values = frame[column].fillna("").astype(str).str.strip()
    values = values.mask(values.eq(""), "未知")
    if mode == "tradable":
        return frame.loc[values.isin(TRADABLE_AVAILABILITIES)]
    label = PURCHASE_AVAILABILITY_LABELS.get(mode)
    if label is None:
        return frame
    return frame.loc[values.eq(label)]


def format_money_text(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number < 0:
        return "---"
    if number >= 800000000:
        return "无限额"
    if number < 10000:
        return f"{number:g}元"
    if number < 100000000:
        return f"{number / 10000:g}万"
    return f"{number / 100000000:g}亿"


def _ensure_purchase_status_columns(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for column in PURCHASE_STATUS_COLUMNS:
        if column not in output.columns:
            output[column] = ""
    output["code"] = output["code"].astype(str).str.zfill(6)
    return output[PURCHASE_STATUS_COLUMNS]
