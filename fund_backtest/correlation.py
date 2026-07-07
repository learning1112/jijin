from __future__ import annotations

import csv
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from .cache import CsvFundCache
from .purchase_status import (
    DEFAULT_PURCHASE_STATUS_PATH,
    PURCHASE_AVAILABILITY_LABELS,
    TRADABLE_AVAILABILITIES,
    load_purchase_status_index,
)
from .screening import (
    DEFAULT_COVERAGE_PATH,
    DEFAULT_MAX_STALE_DAYS,
    filter_coverage,
    load_coverage_index,
)


DEFAULT_CORRELATION_PATH = Path("data/fund_correlations.csv")
DEFAULT_CORRELATION_SUMMARY_PATH = Path("data/fund_correlations_summary.json")
CORRELATION_COLUMNS = [
    "code_a",
    "name_a",
    "fund_type_a",
    "code_b",
    "name_b",
    "fund_type_b",
    "correlation",
    "abs_correlation",
    "sharpe_a",
    "sharpe_b",
    "observations",
]


def compute_correlation_index(
    *,
    coverage_path: str | Path = DEFAULT_COVERAGE_PATH,
    cache_dir: str | Path = "data/fund_cache",
    output_path: str | Path = DEFAULT_CORRELATION_PATH,
    summary_path: str | Path = DEFAULT_CORRELATION_SUMMARY_PATH,
    min_history_years: float = 5.0,
    as_of: str | pd.Timestamp | None = None,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
    min_observations: int = 2,
    limit_funds: int | None = None,
    query: str = "",
    query_a: str = "",
    query_b: str = "",
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    coverage = load_coverage_index(coverage_path)
    if coverage.empty:
        raise ValueError("历史覆盖索引不存在，请先在网页的数据管理里生成。")

    eligible = filter_coverage(
        coverage,
        min_history_years=min_history_years,
        as_of=as_of,
        max_stale_days=max_stale_days,
    )
    eligible = eligible.loc[eligible["data_type"].astype(str) == "accumulated_net_worth"]
    eligible = eligible.drop_duplicates("code").reset_index(drop=True)
    if limit_funds is not None:
        eligible = eligible.head(limit_funds)
    if len(eligible) < 2:
        raise ValueError("满足条件的累计净值基金少于 2 只，无法计算相关性。")

    cache = CsvFundCache(cache_dir)
    names = {
        str(row["code"]).zfill(6): str(row.get("name") or "")
        for _, row in eligible.iterrows()
    }
    fund_types = {
        str(row["code"]).zfill(6): str(row.get("fund_type") or "")
        for _, row in eligible.iterrows()
    }
    eligible_codes = [str(code).zfill(6) for code in eligible["code"]]
    as_of_date = _normalize_as_of(as_of)
    query_a = str(query_a or "").strip()
    query_b = str(query_b or "").strip()
    legacy_query = str(query or "").strip()
    if legacy_query and not query_a and not query_b:
        query_a = legacy_query
    target_codes_a = _find_target_codes(query_a, eligible_codes, names)
    target_codes_b = _find_target_codes(query_b, eligible_codes, names)
    if query_a and not target_codes_a:
        raise ValueError(f"没有找到满足条件的基金A：{query_a}")
    if query_b and not target_codes_b:
        raise ValueError(f"没有找到满足条件的基金B：{query_b}")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if query_a or query_b:
        codes_a = target_codes_a if query_a else eligible_codes
        codes_b = target_codes_b if query_b else eligible_codes
        pair_count = _focused_pair_count(codes_a, codes_b)
        if progress_callback:
            progress_callback(
                {
                    "message": "正在计算指定基金组合的相关性",
                    "current": 0,
                    "total": pair_count,
                    "errors": 0,
                }
            )
        summary = _write_streamed_focused_correlations(
            cache,
            codes_a=codes_a,
            codes_b=codes_b,
            names=names,
            fund_types=fund_types,
            output_path=output_path,
            min_observations=min_observations,
            source_fund_count=len(eligible),
            min_history_years=min_history_years,
            as_of_date=as_of_date,
            query=legacy_query,
            query_a=query_a,
            query_b=query_b,
            progress_callback=progress_callback,
        )
        save_correlation_summary(summary, summary_path)
        return summary

    values: dict[str, pd.Series] = {}
    load_errors: list[dict[str, str]] = []
    total_to_load = int(len(eligible))
    for position, (_, row) in enumerate(eligible.iterrows(), start=1):
        code = str(row["code"]).zfill(6)
        try:
            values[code] = _load_cached_value_series(cache, code, as_of_date)
        except Exception as exc:  # noqa: BLE001
            load_errors.append({"code": code, "error": str(exc)})
        if progress_callback:
            progress_callback(
                {
                    "message": f"正在读取 {code}",
                    "current": position,
                    "total": total_to_load,
                    "errors": len(load_errors),
                }
            )

    if len(values) < 2:
        raise ValueError("可用于计算的累计净值缓存少于 2 只。")

    codes = list(values.keys())
    sharpe_by_code = {code: calculate_sharpe_for_series(series) for code, series in values.items()}

    if progress_callback:
        progress_callback({"message": "正在对齐净值日期", "current": 0, "total": 0, "errors": len(load_errors)})
    aligned = pd.concat(values.values(), axis=1).sort_index().ffill()
    changes = aligned.diff().dropna(how="all")
    if changes.empty:
        raise ValueError("净值变化序列为空，无法计算相关性。")

    if progress_callback:
        progress_callback({"message": "正在计算全量相关矩阵", "current": 0, "total": 0, "errors": len(load_errors)})
    corr = changes[codes].corr(method="pearson", min_periods=min_observations)
    if progress_callback:
        progress_callback({"message": "正在统计有效样本数", "current": 0, "total": 0, "errors": len(load_errors)})
    valid = changes[codes].notna().astype("int64")
    observations = valid.T.dot(valid)

    pair_count = len(codes) * (len(codes) - 1) // 2
    invalid_pairs = 0
    written = 0
    write_path = _temporary_correlation_path(output_path)
    with write_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CORRELATION_COLUMNS)
        writer.writeheader()
        for i, code_a in enumerate(codes):
            for j in range(i + 1, len(codes)):
                code_b = codes[j]
                value = corr.iat[i, j]
                count = int(observations.iat[i, j])
                if not _is_finite_number(value) or count < min_observations:
                    invalid_pairs += 1
                    correlation = ""
                    abs_correlation = ""
                else:
                    correlation = f"{float(value):.12g}"
                    abs_correlation = f"{abs(float(value)):.12g}"
                writer.writerow(
                    {
                        "code_a": code_a,
                        "name_a": names.get(code_a, ""),
                        "fund_type_a": fund_types.get(code_a, ""),
                        "code_b": code_b,
                        "name_b": names.get(code_b, ""),
                        "fund_type_b": fund_types.get(code_b, ""),
                        "correlation": correlation,
                        "abs_correlation": abs_correlation,
                        "sharpe_a": _format_optional_float(sharpe_by_code.get(code_a)),
                        "sharpe_b": _format_optional_float(sharpe_by_code.get(code_b)),
                        "observations": count,
                    }
                )
                written += 1
                if progress_callback and (written % 1000 == 0 or written == pair_count):
                    progress_callback(
                        {
                            "message": "正在写入相关性结果",
                            "current": written,
                            "total": pair_count,
                            "errors": len(load_errors),
                        }
                    )
    write_path.replace(output_path)

    summary = {
        "path": str(output_path),
        "fund_count": int(len(codes)),
        "source_fund_count": int(len(eligible)),
        "pair_count": int(pair_count),
        "rows_written": int(written),
        "invalid_pairs": int(invalid_pairs),
        "load_errors": load_errors[:50],
        "load_error_count": int(len(load_errors)),
        "min_history_years": float(min_history_years),
        "data_type": "accumulated_net_worth",
        "as_of": as_of_date.strftime("%Y-%m-%d") if as_of_date is not None else "",
        "mode": "all_pairs",
        "query": "",
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_correlation_summary(summary, summary_path)
    return summary


def load_correlation_payload(
    *,
    path: str | Path = DEFAULT_CORRELATION_PATH,
    summary_path: str | Path = DEFAULT_CORRELATION_SUMMARY_PATH,
    coverage_path: str | Path = DEFAULT_COVERAGE_PATH,
    purchase_status_path: str | Path = DEFAULT_PURCHASE_STATUS_PATH,
    query: str = "",
    query_a: str = "",
    query_b: str = "",
    sort: str = "abs_desc",
    limit: int = 200,
    page: int = 1,
    page_size: int | None = None,
    corr_min: float | None = None,
    corr_max: float | None = None,
    sharpe_min: float | None = None,
    sharpe_max: float | None = None,
    purchase_availability: str = "",
) -> dict[str, Any]:
    path = Path(path)
    summary = load_correlation_summary(path, summary_path=summary_path)
    if not path.exists():
        return {
            "items": [],
            "summary": summary,
            "warning": "相关性结果不存在，请先在网页里计算。",
        }
    try:
        frame = pd.read_csv(path, dtype=str).fillna("")
    except pd.errors.EmptyDataError:
        return {
            "items": [],
            "summary": summary,
            "warning": "相关性结果正在写入，请稍后刷新。",
        }
    for column in CORRELATION_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    frame["code_a"] = frame["code_a"].astype(str).str.zfill(6)
    frame["code_b"] = frame["code_b"].astype(str).str.zfill(6)
    frame = _attach_correlation_fund_types(frame, coverage_path)
    frame = _attach_correlation_purchase_status(frame, purchase_status_path)
    frame = _filter_and_orient_by_side_queries(frame, query_a=query_a, query_b=query_b)
    frame["_correlation"] = pd.to_numeric(frame["correlation"], errors="coerce")
    frame["_abs_correlation"] = frame["_correlation"].abs()
    frame["_sharpe_a"] = pd.to_numeric(frame["sharpe_a"], errors="coerce")
    frame["_sharpe_b"] = pd.to_numeric(frame["sharpe_b"], errors="coerce")

    q = str(query).strip().lower()
    if q:
        mask = (
            frame["code_a"].str.lower().str.contains(q, na=False, regex=False)
            | frame["code_b"].str.lower().str.contains(q, na=False, regex=False)
            | frame["name_a"].str.lower().str.contains(q, na=False, regex=False)
            | frame["name_b"].str.lower().str.contains(q, na=False, regex=False)
            | frame["fund_type_a"].str.lower().str.contains(q, na=False, regex=False)
            | frame["fund_type_b"].str.lower().str.contains(q, na=False, regex=False)
        )
        frame = frame.loc[mask]

    if corr_min is not None:
        frame = frame.loc[frame["_correlation"] >= corr_min]
    if corr_max is not None:
        frame = frame.loc[frame["_correlation"] < corr_max]
    if sharpe_min is not None or sharpe_max is not None:
        frame = frame.assign(_max_sharpe=frame[["_sharpe_a", "_sharpe_b"]].max(axis=1))
        if sharpe_min is not None:
            frame = frame.loc[frame["_max_sharpe"] >= sharpe_min]
        if sharpe_max is not None:
            frame = frame.loc[frame["_max_sharpe"] < sharpe_max]
    frame = _filter_pair_purchase_availability(frame, purchase_availability)

    if sort == "corr_desc":
        frame = frame.sort_values("_correlation", ascending=False, na_position="last")
    elif sort == "corr_asc":
        frame = frame.sort_values("_correlation", ascending=True, na_position="last")
    elif sort == "sharpe_b_desc":
        frame = frame.sort_values("_sharpe_b", ascending=False, na_position="last")
    elif sort == "sharpe_b_asc":
        frame = frame.sort_values("_sharpe_b", ascending=True, na_position="last")
    elif sort == "abs_asc":
        frame = frame.sort_values("_abs_correlation", ascending=True, na_position="last")
    else:
        frame = frame.sort_values("_abs_correlation", ascending=False, na_position="last")

    page_size = int(page_size if page_size is not None else limit)
    page_size = max(min(page_size, 500), 1)
    total_count = int(len(frame))
    total_pages = max(math.ceil(total_count / page_size), 1)
    page = max(min(int(page), total_pages), 1)
    start = (page - 1) * page_size
    drop_cols = ["_correlation", "_abs_correlation", "_sharpe_a", "_sharpe_b"]
    if "_max_sharpe" in frame.columns:
        drop_cols.append("_max_sharpe")
    limited = frame.iloc[start : start + page_size].drop(columns=drop_cols)
    return {
        "items": limited.to_dict(orient="records"),
        "summary": {
            **summary,
            "filtered_count": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        },
    }


def load_correlation_summary(
    path: str | Path = DEFAULT_CORRELATION_PATH,
    *,
    summary_path: str | Path = DEFAULT_CORRELATION_SUMMARY_PATH,
) -> dict[str, Any]:
    summary_path = Path(summary_path)
    if summary_path.exists():
        with summary_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        if isinstance(payload, dict):
            return payload
    path = Path(path)
    return {
        "path": str(path),
        "fund_count": 0,
        "pair_count": 0,
        "rows_written": 0,
        "invalid_pairs": 0,
        "load_error_count": 0,
        "generated_at": "",
    }


def save_correlation_summary(
    summary: dict[str, Any],
    path: str | Path = DEFAULT_CORRELATION_SUMMARY_PATH,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
    return path


def _attach_correlation_fund_types(frame: pd.DataFrame, coverage_path: str | Path) -> pd.DataFrame:
    if frame.empty:
        return frame
    needs_a = frame["fund_type_a"].astype(str).str.strip().eq("").any()
    needs_b = frame["fund_type_b"].astype(str).str.strip().eq("").any()
    if not needs_a and not needs_b:
        return frame
    coverage_file = Path(coverage_path)
    if not coverage_file.exists():
        return frame
    coverage = load_coverage_index(coverage_file)
    if coverage.empty or "fund_type" not in coverage.columns:
        return frame
    coverage = coverage.drop_duplicates("code").copy()
    coverage["code"] = coverage["code"].astype(str).str.zfill(6)
    type_by_code = coverage.set_index("code")["fund_type"].fillna("").astype(str).to_dict()
    output = frame.copy()
    if needs_a:
        mask = output["fund_type_a"].astype(str).str.strip().eq("")
        output.loc[mask, "fund_type_a"] = output.loc[mask, "code_a"].map(type_by_code).fillna("")
    if needs_b:
        mask = output["fund_type_b"].astype(str).str.strip().eq("")
        output.loc[mask, "fund_type_b"] = output.loc[mask, "code_b"].map(type_by_code).fillna("")
    return output


def _attach_correlation_purchase_status(frame: pd.DataFrame, status_path: str | Path) -> pd.DataFrame:
    output = frame.copy()
    fields = ["availability", "purchase_status", "purchase_limit_text"]
    for suffix in ["a", "b"]:
        for field in fields:
            column = f"{field}_{suffix}"
            if column not in output.columns:
                output[column] = ""
    if output.empty:
        return output

    status_file = Path(status_path)
    if not status_file.exists():
        output["availability_a"] = output["availability_a"].replace("", "未知")
        output["availability_b"] = output["availability_b"].replace("", "未知")
        return output

    status = load_purchase_status_index(status_file)
    if status.empty:
        output["availability_a"] = output["availability_a"].replace("", "未知")
        output["availability_b"] = output["availability_b"].replace("", "未知")
        return output

    status = status.drop_duplicates("code").copy()
    status["code"] = status["code"].astype(str).str.zfill(6)
    by_code = status.set_index("code")
    for suffix, code_column in [("a", "code_a"), ("b", "code_b")]:
        for field in fields:
            column = f"{field}_{suffix}"
            values = output[code_column].map(by_code[field]).fillna("")
            empty = output[column].astype(str).str.strip().eq("")
            output.loc[empty, column] = values.loc[empty]
        availability_column = f"availability_{suffix}"
        output.loc[output[availability_column].astype(str).str.strip().eq(""), availability_column] = "未知"
    return output


def _filter_and_orient_by_side_queries(frame: pd.DataFrame, *, query_a: str = "", query_b: str = "") -> pd.DataFrame:
    q_a = str(query_a or "").strip().lower()
    q_b = str(query_b or "").strip().lower()
    if frame.empty or (not q_a and not q_b):
        return frame

    if q_a and q_b:
        direct = frame.loc[_side_match(frame, "a", q_a) & _side_match(frame, "b", q_b)]
        reversed_rows = _swap_correlation_sides(
            frame.loc[_side_match(frame, "a", q_b) & _side_match(frame, "b", q_a)]
        )
        return _deduplicate_oriented_rows(pd.concat([direct, reversed_rows], ignore_index=True))

    if q_a:
        direct = frame.loc[_side_match(frame, "a", q_a)]
        reversed_rows = _swap_correlation_sides(frame.loc[_side_match(frame, "b", q_a)])
        return _deduplicate_oriented_rows(pd.concat([direct, reversed_rows], ignore_index=True))

    direct = frame.loc[_side_match(frame, "b", q_b)]
    reversed_rows = _swap_correlation_sides(frame.loc[_side_match(frame, "a", q_b)])
    return _deduplicate_oriented_rows(pd.concat([direct, reversed_rows], ignore_index=True))


def _side_match(frame: pd.DataFrame, suffix: str, query: str) -> pd.Series:
    if not query:
        return pd.Series(True, index=frame.index)
    columns = [f"code_{suffix}", f"name_{suffix}", f"fund_type_{suffix}"]
    mask = pd.Series(False, index=frame.index)
    for column in columns:
        if column in frame.columns:
            mask = mask | frame[column].fillna("").astype(str).str.lower().str.contains(query, na=False, regex=False)
    return mask


def _swap_correlation_sides(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    left_columns = [column for column in output.columns if column.endswith("_a") and f"{column[:-2]}_b" in output.columns]
    for left_column in left_columns:
        right_column = f"{left_column[:-2]}_b"
        left_values = output[left_column].copy()
        output[left_column] = output[right_column]
        output[right_column] = left_values
    return output


def _deduplicate_oriented_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    return frame.drop_duplicates(["code_a", "code_b"]).reset_index(drop=True)


def _filter_pair_purchase_availability(frame: pd.DataFrame, availability_filter: str) -> pd.DataFrame:
    mode = str(availability_filter or "").strip()
    if mode in {"", "all"} or frame.empty:
        return frame
    right = _availability_series(frame.get("availability_b"))
    if mode == "tradable":
        return frame.loc[right.isin(TRADABLE_AVAILABILITIES)]
    if mode == "both_open":
        return frame.loc[right.eq("可购买")]
    label = PURCHASE_AVAILABILITY_LABELS.get(mode)
    if label:
        return frame.loc[right.eq(label)]
    return frame


def _availability_series(series: pd.Series | None) -> pd.Series:
    if series is None:
        return pd.Series(dtype=str)
    values = series.fillna("").astype(str).str.strip()
    return values.mask(values.eq(""), "未知")


def _write_streamed_focused_correlations(
    cache: CsvFundCache,
    *,
    codes_a: list[str],
    codes_b: list[str],
    names: dict[str, str],
    fund_types: dict[str, str],
    output_path: Path,
    min_observations: int,
    source_fund_count: int,
    min_history_years: float,
    as_of_date: pd.Timestamp | None,
    query: str,
    query_a: str,
    query_b: str,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    pair_count = _focused_pair_count(codes_a, codes_b)
    load_errors: list[dict[str, str]] = []
    failed_codes: set[str] = set()
    sharpe_by_code: dict[str, float | None] = {}
    codes_a_set = set(codes_a)
    codes_b_set = set(codes_b)

    def remember_error(code: str, exc: Exception) -> None:
        if code in failed_codes:
            return
        failed_codes.add(code)
        load_errors.append({"code": code, "error": str(exc)})

    def load_optional(code: str) -> pd.Series | None:
        if code in failed_codes:
            return None
        try:
            return _load_cached_value_series(cache, code, as_of_date)
        except Exception as exc:  # noqa: BLE001
            remember_error(code, exc)
            return None

    def sharpe_for(code: str, values: pd.Series) -> float | None:
        if code not in sharpe_by_code:
            sharpe_by_code[code] = calculate_sharpe_for_series(values)
        return sharpe_by_code[code]

    values_a: dict[str, pd.Series] = {}
    values_b: dict[str, pd.Series] = {}
    if query_a:
        for code in codes_a:
            values = load_optional(code)
            if values is not None:
                values_a[code] = values
        if not values_a:
            raise ValueError(f"基金A没有可用的累计净值缓存：{query_a}")
    if query_b:
        for code in codes_b:
            values = load_optional(code)
            if values is not None:
                values_b[code] = values
        if not values_b:
            raise ValueError(f"基金B没有可用的累计净值缓存：{query_b}")

    processed = 0
    invalid_pairs = 0
    written = 0
    write_path = _temporary_correlation_path(output_path)
    with write_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CORRELATION_COLUMNS)
        writer.writeheader()
        for code_a in codes_a:
            left = values_a.get(code_a)
            if left is None:
                left = values_b.get(code_a)
            if left is None:
                left = load_optional(code_a)
            if left is None:
                continue
            for code_b in codes_b:
                if code_a == code_b:
                    continue
                if code_a in codes_b_set and code_b in codes_a_set and code_a > code_b:
                    continue
                processed += 1
                right = values_b.get(code_b)
                if right is None:
                    right = values_a.get(code_b)
                if right is None:
                    right = load_optional(code_b)
                if right is None:
                    if progress_callback and (processed % 500 == 0 or processed == pair_count):
                        progress_callback(
                            {
                                "message": "正在写入相关性结果",
                                "current": processed,
                                "total": pair_count,
                                "errors": len(load_errors),
                            }
                        )
                    continue

                value, count = _pair_correlation(left, right, min_observations=min_observations)
                if not _is_finite_number(value) or count < min_observations:
                    invalid_pairs += 1
                    correlation = ""
                    abs_correlation = ""
                else:
                    correlation = f"{float(value):.12g}"
                    abs_correlation = f"{abs(float(value)):.12g}"
                writer.writerow(
                    {
                        "code_a": code_a,
                        "name_a": names.get(code_a, ""),
                        "fund_type_a": fund_types.get(code_a, ""),
                        "code_b": code_b,
                        "name_b": names.get(code_b, ""),
                        "fund_type_b": fund_types.get(code_b, ""),
                        "correlation": correlation,
                        "abs_correlation": abs_correlation,
                        "sharpe_a": _format_optional_float(sharpe_for(code_a, left)),
                        "sharpe_b": _format_optional_float(sharpe_for(code_b, right)),
                        "observations": count,
                    }
                )
                written += 1
                if progress_callback and (processed % 500 == 0 or processed == pair_count):
                    progress_callback(
                        {
                            "message": "正在写入相关性结果",
                            "current": processed,
                            "total": pair_count,
                            "errors": len(load_errors),
                        }
                    )
    write_path.replace(output_path)

    return {
        "path": str(output_path),
        "fund_count": int(len(set(codes_a).union(codes_b))),
        "source_fund_count": int(source_fund_count),
        "comparison_fund_count": int(len(set(codes_a).union(codes_b))),
        "fund_count_a": int(len(codes_a)),
        "fund_count_b": int(len(codes_b)),
        "pair_count": int(written),
        "rows_written": int(written),
        "invalid_pairs": int(invalid_pairs),
        "load_errors": load_errors[:50],
        "load_error_count": int(len(load_errors)),
        "min_history_years": float(min_history_years),
        "data_type": "accumulated_net_worth",
        "as_of": as_of_date.strftime("%Y-%m-%d") if as_of_date is not None else "",
        "mode": "focused",
        "query": str(query).strip(),
        "query_a": str(query_a).strip(),
        "query_b": str(query_b).strip(),
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _write_focused_correlations(
    values: dict[str, pd.Series],
    *,
    codes_a: list[str],
    codes_b: list[str],
    names: dict[str, str],
    fund_types: dict[str, str],
    sharpe_by_code: dict[str, float | None],
    output_path: Path,
    min_observations: int,
    load_errors: list[dict[str, str]],
    source_fund_count: int,
    min_history_years: float,
    as_of_date: pd.Timestamp | None,
    query: str,
    query_a: str,
    query_b: str,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    pair_count = _focused_pair_count(codes_a, codes_b)
    invalid_pairs = 0
    written = 0
    codes_a_set = set(codes_a)
    codes_b_set = set(codes_b)
    write_path = _temporary_correlation_path(output_path)
    with write_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CORRELATION_COLUMNS)
        writer.writeheader()
        for code_a in codes_a:
            for code_b in codes_b:
                if code_a == code_b:
                    continue
                if code_a in codes_b_set and code_b in codes_a_set and code_a > code_b:
                    continue
                value, count = _pair_correlation(values[code_a], values[code_b], min_observations=min_observations)
                if not _is_finite_number(value) or count < min_observations:
                    invalid_pairs += 1
                    correlation = ""
                    abs_correlation = ""
                else:
                    correlation = f"{float(value):.12g}"
                    abs_correlation = f"{abs(float(value)):.12g}"
                writer.writerow(
                    {
                        "code_a": code_a,
                        "name_a": names.get(code_a, ""),
                        "fund_type_a": fund_types.get(code_a, ""),
                        "code_b": code_b,
                        "name_b": names.get(code_b, ""),
                        "fund_type_b": fund_types.get(code_b, ""),
                        "correlation": correlation,
                        "abs_correlation": abs_correlation,
                        "sharpe_a": _format_optional_float(sharpe_by_code.get(code_a)),
                        "sharpe_b": _format_optional_float(sharpe_by_code.get(code_b)),
                        "observations": count,
                    }
                )
                written += 1
                if progress_callback and (written % 500 == 0 or written == pair_count):
                    progress_callback(
                        {
                            "message": "正在写入相关性结果",
                            "current": written,
                            "total": pair_count,
                            "errors": len(load_errors),
                        }
                    )
    write_path.replace(output_path)

    return {
        "path": str(output_path),
        "fund_count": int(len(set(codes_a).union(codes_b))),
        "source_fund_count": int(source_fund_count),
        "comparison_fund_count": int(len(set(codes_a).union(codes_b))),
        "fund_count_a": int(len(codes_a)),
        "fund_count_b": int(len(codes_b)),
        "pair_count": int(written),
        "rows_written": int(written),
        "invalid_pairs": int(invalid_pairs),
        "load_errors": load_errors[:50],
        "load_error_count": int(len(load_errors)),
        "min_history_years": float(min_history_years),
        "data_type": "accumulated_net_worth",
        "as_of": as_of_date.strftime("%Y-%m-%d") if as_of_date is not None else "",
        "mode": "focused",
        "query": str(query).strip(),
        "query_a": str(query_a).strip(),
        "query_b": str(query_b).strip(),
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _find_target_codes(query: str, codes: list[str], names: dict[str, str]) -> list[str]:
    q = str(query).strip().lower()
    if not q:
        return []
    exact = str(q).zfill(6) if q.isdigit() else q
    if exact in codes:
        return [exact]
    exact_name_matches = [
        code
        for code in codes
        if names.get(code, "").strip().lower() == q
    ]
    if exact_name_matches:
        return exact_name_matches
    return [
        code
        for code in codes
        if q in code.lower() or q in names.get(code, "").lower()
    ]


def _focused_pair_count(codes_a: list[str], codes_b: list[str]) -> int:
    set_a = set(codes_a)
    set_b = set(codes_b)
    overlap = len(set_a & set_b)
    return int(len(set_a) * len(set_b) - overlap - (overlap * (overlap - 1) // 2))


def _temporary_correlation_path(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.name}.tmp")


def _load_cached_value_series(cache: CsvFundCache, code: str, as_of_date: pd.Timestamp | None) -> pd.Series:
    series = cache.load(code)
    if series is None:
        raise ValueError("缓存中没有历史净值数据")
    if series.data_type != "accumulated_net_worth":
        raise ValueError(f"缓存数据不是累计净值：{series.data_type}")
    frame = series.frame.copy()
    if as_of_date is not None:
        frame = frame.loc[frame.index <= as_of_date]
    if frame.empty or "value" not in frame.columns:
        raise ValueError("历史净值为空")
    value_series = pd.to_numeric(frame["value"], errors="coerce").dropna()
    if value_series.empty:
        raise ValueError("历史净值为空")
    value_series.name = code
    return value_series


def calculate_sharpe_by_code(returns: pd.DataFrame, *, periods_per_year: int = 252) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for code in returns.columns:
        values = [
            float(value)
            for value in pd.to_numeric(returns[code], errors="coerce").dropna().tolist()
            if _is_finite_number(value)
        ]
        if len(values) < 2:
            result[str(code)] = None
            continue
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
        std = math.sqrt(variance) if variance > 0 else 0.0
        if not math.isfinite(std) or std <= 0:
            result[str(code)] = None
            continue
        sharpe = (mean / std) * math.sqrt(periods_per_year)
        result[str(code)] = sharpe if math.isfinite(sharpe) else None
    return result


def calculate_sharpe_for_series(values: pd.Series, *, periods_per_year: int = 252) -> float | None:
    series = pd.to_numeric(values, errors="coerce").dropna()
    returns = series / series.shift(1) - 1
    return calculate_sharpe_by_code(pd.DataFrame({"value": returns}), periods_per_year=periods_per_year)["value"]


def _pair_correlation(
    left: pd.Series,
    right: pd.Series,
    *,
    min_observations: int,
) -> tuple[float | None, int]:
    pair = pd.concat([left, right], axis=1).sort_index().ffill()
    changes = pair.diff().dropna()
    count = int(len(changes))
    if count < min_observations:
        return None, count
    value = _pearson_correlation(changes.iloc[:, 0], changes.iloc[:, 1])
    return (float(value), count) if _is_finite_number(value) else (None, count)


def _pearson_correlation(left: pd.Series, right: pd.Series) -> float | None:
    pairs: list[tuple[float, float]] = []
    for left_value, right_value in zip(left.tolist(), right.tolist()):
        if not _is_finite_number(left_value) or not _is_finite_number(right_value):
            continue
        pairs.append((float(left_value), float(right_value)))
    count = len(pairs)
    if count < 2:
        return None
    sum_x = sum(x for x, _ in pairs)
    sum_y = sum(y for _, y in pairs)
    sum_x2 = sum(x * x for x, _ in pairs)
    sum_y2 = sum(y * y for _, y in pairs)
    sum_xy = sum(x * y for x, y in pairs)
    numerator = count * sum_xy - sum_x * sum_y
    denom_x = count * sum_x2 - sum_x * sum_x
    denom_y = count * sum_y2 - sum_y * sum_y
    if denom_x <= 0 or denom_y <= 0:
        return None
    value = numerator / math.sqrt(denom_x * denom_y)
    if value > 1 and value < 1 + 1e-12:
        return 1.0
    if value < -1 and value > -1 - 1e-12:
        return -1.0
    return value


def _normalize_as_of(value: str | pd.Timestamp | None) -> pd.Timestamp | None:
    if value is None or str(value).strip() == "":
        return None
    return pd.Timestamp(value).normalize()


def _is_finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _format_optional_float(value: float | None) -> str:
    if value is None or not math.isfinite(float(value)):
        return ""
    return f"{float(value):.12g}"
