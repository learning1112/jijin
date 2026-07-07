from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from .correlation import DEFAULT_CORRELATION_PATH, load_correlation_summary
from .eastmoney import EastmoneyFundClient
from .purchase_status import (
    DEFAULT_PURCHASE_STATUS_PATH,
    load_purchase_status_index,
    refresh_purchase_status_index,
)
from .screening import (
    DEFAULT_COVERAGE_PATH,
    DEFAULT_MAX_STALE_DAYS,
    load_coverage_index,
    load_fund_catalog,
    update_coverage_index,
)


DEFAULT_FUND_CODES_PATH = Path("data/fund_codes.csv")


def refresh_fund_catalog(
    *,
    output_path: str | Path = DEFAULT_FUND_CODES_PATH,
    client: EastmoneyFundClient | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if progress_callback:
        progress_callback({"message": "正在获取基金列表", "current": 0, "total": 1})
    client = client or EastmoneyFundClient()
    infos = client.fetch_fund_codes()
    frame = pd.DataFrame([info.__dict__ for info in infos])
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False, encoding="utf-8-sig")
    result = {
        "path": str(output_path),
        "count": int(len(frame)),
        "updated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if progress_callback:
        progress_callback({"message": "基金列表已更新", "current": 1, "total": 1})
    return result


def build_coverage_index(
    *,
    catalog_paths: Iterable[str | Path] | None = None,
    cache_dir: str | Path = "data/fund_cache",
    coverage_path: str | Path = DEFAULT_COVERAGE_PATH,
    client: EastmoneyFundClient | None = None,
    as_of: str | pd.Timestamp | None = None,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
    refresh: bool = False,
    limit: int | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    catalog = load_fund_catalog(catalog_paths)
    if catalog.empty:
        raise ValueError("基金列表不存在，请先在网页的数据管理里更新基金列表。")
    if progress_callback:
        progress_callback(
            {
                "message": "开始生成历史覆盖索引",
                "current": 0,
                "total": int(len(catalog) if limit is None else min(limit, len(catalog))),
            }
        )
    coverage = update_coverage_index(
        catalog,
        cache_dir=cache_dir,
        coverage_path=coverage_path,
        client=client or EastmoneyFundClient(),
        as_of=as_of,
        max_stale_days=max_stale_days,
        refresh=refresh,
        limit=limit,
        progress_callback=progress_callback,
    )
    errors = int((coverage["error"].astype(str) != "").sum()) if "error" in coverage else 0
    return {
        "path": str(coverage_path),
        "count": int(len(coverage)),
        "errors": errors,
        "as_of": str(as_of or pd.Timestamp.today().normalize().strftime("%Y-%m-%d")),
        "updated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def refresh_purchase_status(
    *,
    output_path: str | Path = DEFAULT_PURCHASE_STATUS_PATH,
    client: EastmoneyFundClient | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    frame = refresh_purchase_status_index(
        output_path=output_path,
        client=client or EastmoneyFundClient(),
        progress_callback=progress_callback,
    )
    return {
        "path": str(output_path),
        "count": int(len(frame)),
        "updated_at": _latest_text(frame.get("checked_at")),
    }


def get_data_status(
    *,
    coverage_path: str | Path = DEFAULT_COVERAGE_PATH,
    correlation_path: str | Path = DEFAULT_CORRELATION_PATH,
    purchase_status_path: str | Path = DEFAULT_PURCHASE_STATUS_PATH,
) -> dict[str, Any]:
    catalog = load_fund_catalog()
    coverage_path = Path(coverage_path)
    coverage = load_coverage_index(coverage_path)
    correlation_path = Path(correlation_path)
    correlation_summary = load_correlation_summary(correlation_path)
    purchase_status_path = Path(purchase_status_path)
    purchase_status = load_purchase_status_index(purchase_status_path)
    return {
        "fund_catalog": {
            "exists": not catalog.empty,
            "count": int(len(catalog)),
        },
        "coverage": {
            "exists": coverage_path.exists(),
            "path": str(coverage_path),
            "count": int(len(coverage)),
            "errors": int((coverage["error"].astype(str) != "").sum()) if not coverage.empty else 0,
            "latest_checked_at": _latest_text(coverage.get("checked_at")),
        },
        "correlations": {
            "exists": correlation_path.exists(),
            "path": str(correlation_path),
            **correlation_summary,
        },
        "purchase_status": {
            "exists": purchase_status_path.exists(),
            "path": str(purchase_status_path),
            "count": int(len(purchase_status)),
            "latest_checked_at": _latest_text(purchase_status.get("checked_at")),
        },
    }


def _latest_text(series: pd.Series | None) -> str:
    if series is None or series.empty:
        return ""
    values = series.astype(str).loc[series.astype(str) != ""]
    if values.empty:
        return ""
    return str(values.max())
