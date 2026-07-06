from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from .cache import CsvFundCache
from .eastmoney import EastmoneyFundClient, FundSeries


DEFAULT_COVERAGE_PATH = Path("data/fund_coverage.csv")
DEFAULT_MAX_STALE_DAYS = 45
COVERAGE_COLUMNS = [
    "code",
    "name",
    "fund_type",
    "pinyin",
    "data_type",
    "data_start",
    "data_end",
    "history_years",
    "has_5y",
    "has_10y",
    "is_active",
    "as_of",
    "checked_at",
    "error",
]


def load_fund_catalog(paths: Iterable[str | Path] | None = None) -> pd.DataFrame:
    candidates = [Path(path) for path in paths] if paths is not None else [
        Path("data/fund_codes.csv"),
        Path("基金列表.csv"),
    ]
    for path in candidates:
        if not path.exists():
            continue
        frame = pd.read_csv(path, dtype=str).fillna("")
        if "基金代码" in frame.columns:
            frame = frame.rename(
                columns={
                    "基金代码": "code",
                    "基金简称": "name",
                    "基金类型": "fund_type",
                    "基金拼音": "pinyin",
                }
            )
        if "abbreviation" in frame.columns and "pinyin" not in frame.columns:
            frame["pinyin"] = frame["abbreviation"]
        if "code" not in frame.columns:
            continue
        for column in ["name", "fund_type", "pinyin"]:
            if column not in frame.columns:
                frame[column] = ""
        frame["code"] = frame["code"].astype(str).str.zfill(6)
        return frame[["code", "name", "fund_type", "pinyin"]].drop_duplicates("code")
    return pd.DataFrame(columns=["code", "name", "fund_type", "pinyin"])


def update_coverage_index(
    catalog: pd.DataFrame,
    *,
    cache_dir: str | Path = "data/fund_cache",
    coverage_path: str | Path = DEFAULT_COVERAGE_PATH,
    client: EastmoneyFundClient | None = None,
    as_of: str | pd.Timestamp | None = None,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
    refresh: bool = False,
    limit: int | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> pd.DataFrame:
    as_of_date = normalize_as_of(as_of)
    client = client or EastmoneyFundClient()
    cache = CsvFundCache(cache_dir)
    coverage_path = Path(coverage_path)
    existing = load_coverage_index(coverage_path)
    rows_by_code = {
        str(row["code"]).zfill(6): _coverage_dict(row)
        for _, row in existing.iterrows()
    }
    catalog_rows = catalog.head(limit) if limit is not None else catalog

    total = len(catalog_rows)
    errors = 0
    for position, (_, catalog_row) in enumerate(catalog_rows.iterrows(), start=1):
        info = _catalog_dict(catalog_row)
        current = rows_by_code.get(info["code"])
        if not refresh and current and _has_stored_coverage(current):
            row = recompute_coverage_flags(
                current,
                as_of=as_of_date,
                max_stale_days=max_stale_days,
                catalog_info=info,
            )
        else:
            row = fetch_coverage_row(
                info,
                cache=cache,
                client=client,
                as_of=as_of_date,
                max_stale_days=max_stale_days,
                refresh=refresh,
            )
        rows_by_code[info["code"]] = row
        save_coverage_index(pd.DataFrame(rows_by_code.values()), coverage_path)
        if row.get("error"):
            errors += 1
        if progress_callback:
            progress_callback(
                {
                    "current": position,
                    "total": total,
                    "code": info["code"],
                    "errors": errors,
                    "message": f"正在检查 {info['code']}",
                }
            )

    result = pd.DataFrame(rows_by_code.values())
    result = _ensure_coverage_columns(result)
    save_coverage_index(result, coverage_path)
    return result


def fetch_coverage_row(
    catalog_info: dict[str, str],
    *,
    cache: CsvFundCache,
    client: EastmoneyFundClient,
    as_of: pd.Timestamp,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
    refresh: bool = False,
) -> dict[str, Any]:
    checked_at = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        series = cache.get_or_fetch(catalog_info["code"], client=client, refresh=refresh)
        row = coverage_row_from_series(
            catalog_info,
            series,
            as_of=as_of,
            max_stale_days=max_stale_days,
        )
        row["checked_at"] = checked_at
        return row
    except Exception as exc:  # noqa: BLE001
        row = _base_coverage_row(catalog_info, as_of=as_of)
        row["checked_at"] = checked_at
        row["error"] = str(exc)
        return row


def coverage_row_from_series(
    catalog_info: dict[str, str],
    series: FundSeries,
    *,
    as_of: str | pd.Timestamp | None = None,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
) -> dict[str, Any]:
    as_of_date = normalize_as_of(as_of)
    row = _base_coverage_row(catalog_info, as_of=as_of_date)
    values = series.frame.dropna(subset=["value"]) if "value" in series.frame.columns else series.frame
    if values.empty:
        row["data_type"] = series.data_type
        row["error"] = "No historical values."
        return row

    row["data_type"] = series.data_type
    row["data_start"] = _date_text(values.index.min())
    row["data_end"] = _date_text(values.index.max())
    row["error"] = ""
    return recompute_coverage_flags(row, as_of=as_of_date, max_stale_days=max_stale_days)


def recompute_coverage_flags(
    row: dict[str, Any],
    *,
    as_of: str | pd.Timestamp | None = None,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
    catalog_info: dict[str, str] | None = None,
) -> dict[str, Any]:
    as_of_date = normalize_as_of(as_of)
    updated = dict(row)
    if catalog_info:
        updated.update(
            {
                key: catalog_info.get(key, updated.get(key, ""))
                for key in ["code", "name", "fund_type", "pinyin"]
            }
        )
    updated["code"] = str(updated.get("code", "")).zfill(6)
    updated["as_of"] = _date_text(as_of_date)

    data_start = _parse_timestamp(updated.get("data_start"))
    data_end = _parse_timestamp(updated.get("data_end"))
    error = str(updated.get("error") or "")
    if data_start is None or data_end is None or error:
        updated["history_years"] = 0.0
        updated["is_active"] = False
        updated["has_5y"] = False
        updated["has_10y"] = False
        return _ensure_row_columns(updated)

    updated["history_years"] = round(max((as_of_date - data_start).days, 0) / 365.25, 2)
    updated["is_active"] = bool(data_end >= as_of_date - pd.Timedelta(days=max_stale_days))
    updated["has_5y"] = bool(_meets_history_years(data_start, data_end, as_of_date, 5, max_stale_days))
    updated["has_10y"] = bool(_meets_history_years(data_start, data_end, as_of_date, 10, max_stale_days))
    return _ensure_row_columns(updated)


def filter_coverage(
    coverage: pd.DataFrame,
    *,
    min_history_years: float = 0.0,
    as_of: str | pd.Timestamp | None = None,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
) -> pd.DataFrame:
    if coverage.empty:
        return _ensure_coverage_columns(coverage)
    recomputed = pd.DataFrame(
        [
            recompute_coverage_flags(
                _coverage_dict(row),
                as_of=as_of,
                max_stale_days=max_stale_days,
            )
            for _, row in coverage.iterrows()
        ]
    )
    if min_history_years <= 0:
        return _ensure_coverage_columns(recomputed)
    return recomputed.loc[
        recomputed.apply(
            lambda row: coverage_row_meets_requirement(
                row,
                min_history_years=min_history_years,
                as_of=as_of,
                max_stale_days=max_stale_days,
            ),
            axis=1,
        )
    ].reset_index(drop=True)


def coverage_row_meets_requirement(
    row: pd.Series | dict[str, Any],
    *,
    min_history_years: float,
    as_of: str | pd.Timestamp | None = None,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
) -> bool:
    if min_history_years <= 0:
        return True
    data_start = _parse_timestamp(row.get("data_start"))
    data_end = _parse_timestamp(row.get("data_end"))
    if data_start is None or data_end is None or str(row.get("error") or ""):
        return False
    return _meets_history_years(
        data_start,
        data_end,
        normalize_as_of(as_of),
        float(min_history_years),
        max_stale_days,
    )


def validate_fund_history_requirement(
    codes: Iterable[str],
    *,
    min_history_years: float,
    as_of: str | pd.Timestamp | None = None,
    coverage_path: str | Path = DEFAULT_COVERAGE_PATH,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
) -> None:
    if min_history_years <= 0:
        return
    coverage = load_coverage_index(coverage_path)
    if coverage.empty:
        raise ValueError(
            "历史覆盖索引不存在，请在网页的数据管理里生成 data/fund_coverage.csv。"
        )

    as_of_date = normalize_as_of(as_of)
    coverage_by_code = {
        str(row["code"]).zfill(6): recompute_coverage_flags(
            _coverage_dict(row),
            as_of=as_of_date,
            max_stale_days=max_stale_days,
        )
        for _, row in coverage.iterrows()
    }
    failures: list[str] = []
    for code in codes:
        normalized = str(code).zfill(6)
        row = coverage_by_code.get(normalized)
        if not row:
            failures.append(f"{normalized} 没有历史覆盖记录")
            continue
        if coverage_row_meets_requirement(
            row,
            min_history_years=min_history_years,
            as_of=as_of_date,
            max_stale_days=max_stale_days,
        ):
            continue
        start = row.get("data_start") or "未知"
        end = row.get("data_end") or "未知"
        error = row.get("error")
        suffix = f"，错误：{error}" if error else ""
        failures.append(
            f"{normalized} 数据从 {start} 开始，最新到 {end}，不满足 {min_history_years:g} 年要求{suffix}"
        )
    if failures:
        raise ValueError("；".join(failures))


def load_coverage_index(path: str | Path = DEFAULT_COVERAGE_PATH) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=COVERAGE_COLUMNS)
    frame = pd.read_csv(path, dtype=str).fillna("")
    if "code" in frame.columns:
        frame["code"] = frame["code"].astype(str).str.zfill(6)
    return _ensure_coverage_columns(frame)


def save_coverage_index(frame: pd.DataFrame, path: str | Path = DEFAULT_COVERAGE_PATH) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    output = _ensure_coverage_columns(frame)
    output.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def normalize_as_of(value: str | pd.Timestamp | None) -> pd.Timestamp:
    if value is None or str(value).strip() == "":
        return pd.Timestamp.today().normalize()
    return pd.Timestamp(value).normalize()


def _meets_history_years(
    data_start: pd.Timestamp,
    data_end: pd.Timestamp,
    as_of: pd.Timestamp,
    years: float,
    max_stale_days: int,
) -> bool:
    whole_years = int(years)
    if years == whole_years:
        required_start = as_of - pd.DateOffset(years=whole_years)
    else:
        required_start = as_of - pd.Timedelta(days=round(years * 365.25))
    active = data_end >= as_of - pd.Timedelta(days=max_stale_days)
    return bool(active and data_start <= required_start)


def _base_coverage_row(catalog_info: dict[str, str], *, as_of: pd.Timestamp) -> dict[str, Any]:
    return {
        "code": str(catalog_info.get("code", "")).zfill(6),
        "name": catalog_info.get("name", ""),
        "fund_type": catalog_info.get("fund_type", ""),
        "pinyin": catalog_info.get("pinyin", ""),
        "data_type": "",
        "data_start": "",
        "data_end": "",
        "history_years": 0.0,
        "has_5y": False,
        "has_10y": False,
        "is_active": False,
        "as_of": _date_text(as_of),
        "checked_at": "",
        "error": "",
    }


def _catalog_dict(row: pd.Series) -> dict[str, str]:
    return {
        "code": str(row.get("code", "")).zfill(6),
        "name": str(row.get("name", "")),
        "fund_type": str(row.get("fund_type", "")),
        "pinyin": str(row.get("pinyin", "")),
    }


def _coverage_dict(row: pd.Series) -> dict[str, Any]:
    return {column: row.get(column, "") for column in row.index}


def _has_stored_coverage(row: dict[str, Any]) -> bool:
    return bool(row.get("data_start") and row.get("data_end")) or bool(row.get("error"))


def _ensure_coverage_columns(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for column in COVERAGE_COLUMNS:
        if column not in output.columns:
            output[column] = ""
    if "code" in output.columns:
        output["code"] = output["code"].astype(str).str.zfill(6)
    return output[COVERAGE_COLUMNS]


def _ensure_row_columns(row: dict[str, Any]) -> dict[str, Any]:
    return {column: row.get(column, "") for column in COVERAGE_COLUMNS}


def _parse_timestamp(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    timestamp = pd.Timestamp(text)
    if pd.isna(timestamp):
        return None
    return timestamp.normalize()


def _date_text(value: Any) -> str:
    return pd.Timestamp(value).normalize().strftime("%Y-%m-%d")
