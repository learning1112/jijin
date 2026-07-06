from __future__ import annotations

import csv
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from .cache import CsvFundCache
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
    "code_b",
    "name_b",
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
    eligible_codes = [str(code).zfill(6) for code in eligible["code"]]
    values: dict[str, pd.Series] = {}
    load_errors: list[dict[str, str]] = []
    as_of_date = _normalize_as_of(as_of)
    total_to_load = int(len(eligible))
    for position, (_, row) in enumerate(eligible.iterrows(), start=1):
        code = str(row["code"]).zfill(6)
        try:
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
            values[code] = value_series
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
    target_codes = _find_target_codes(query, eligible_codes, names)
    target_codes = [code for code in target_codes if code in values]
    if query and not target_codes:
        raise ValueError(f"没有找到满足条件的累计净值基金：{query}")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if target_codes:
        if progress_callback:
            progress_callback(
                {
                    "message": f"正在计算 {', '.join(target_codes[:3])} 的相关性",
                    "current": 0,
                    "total": len(target_codes) * max(len(codes) - 1, 0),
                    "errors": len(load_errors),
                }
            )
        summary = _write_focused_correlations(
            values,
            target_codes=target_codes,
            names=names,
            sharpe_by_code=sharpe_by_code,
            output_path=output_path,
            min_observations=min_observations,
            load_errors=load_errors,
            source_fund_count=len(eligible),
            min_history_years=min_history_years,
            as_of_date=as_of_date,
            query=query,
            progress_callback=progress_callback,
        )
        save_correlation_summary(summary, summary_path)
        return summary

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
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
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
                        "code_b": code_b,
                        "name_b": names.get(code_b, ""),
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
    query: str = "",
    sort: str = "abs_desc",
    limit: int = 200,
    page: int = 1,
    page_size: int | None = None,
    corr_min: float | None = None,
    corr_max: float | None = None,
    sharpe_min: float | None = None,
    sharpe_max: float | None = None,
) -> dict[str, Any]:
    path = Path(path)
    summary = load_correlation_summary(path, summary_path=summary_path)
    if not path.exists():
        return {
            "items": [],
            "summary": summary,
            "warning": "相关性结果不存在，请先在网页里计算。",
        }
    frame = pd.read_csv(path, dtype=str).fillna("")
    for column in CORRELATION_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    frame["code_a"] = frame["code_a"].astype(str).str.zfill(6)
    frame["code_b"] = frame["code_b"].astype(str).str.zfill(6)
    frame["_correlation"] = pd.to_numeric(frame["correlation"], errors="coerce")
    frame["_abs_correlation"] = frame["_correlation"].abs()
    frame["_sharpe_a"] = pd.to_numeric(frame["sharpe_a"], errors="coerce")
    frame["_sharpe_b"] = pd.to_numeric(frame["sharpe_b"], errors="coerce")

    q = str(query).strip().lower()
    if q:
        mask = (
            frame["code_a"].str.lower().str.contains(q, na=False)
            | frame["code_b"].str.lower().str.contains(q, na=False)
            | frame["name_a"].str.lower().str.contains(q, na=False)
            | frame["name_b"].str.lower().str.contains(q, na=False)
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

    if sort == "corr_desc":
        frame = frame.sort_values("_correlation", ascending=False, na_position="last")
    elif sort == "corr_asc":
        frame = frame.sort_values("_correlation", ascending=True, na_position="last")
    elif sort == "sharpe_b_desc":
        frame = frame.sort_values("_sharpe_b", ascending=False, na_position="last")
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


def _write_focused_correlations(
    values: dict[str, pd.Series],
    *,
    target_codes: list[str],
    names: dict[str, str],
    sharpe_by_code: dict[str, float | None],
    output_path: Path,
    min_observations: int,
    load_errors: list[dict[str, str]],
    source_fund_count: int,
    min_history_years: float,
    as_of_date: pd.Timestamp | None,
    query: str,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    codes = list(values.keys())
    expected_pairs = {
        tuple(sorted((target, other)))
        for target in target_codes
        for other in codes
        if other != target
    }
    pair_count = len(expected_pairs)
    invalid_pairs = 0
    written = 0
    seen_pairs: set[tuple[str, str]] = set()
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CORRELATION_COLUMNS)
        writer.writeheader()
        for target in target_codes:
            for other in codes:
                if other == target:
                    continue
                pair_key = tuple(sorted((target, other)))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                value, count = _pair_correlation(values[target], values[other], min_observations=min_observations)
                if not _is_finite_number(value) or count < min_observations:
                    invalid_pairs += 1
                    correlation = ""
                    abs_correlation = ""
                else:
                    correlation = f"{float(value):.12g}"
                    abs_correlation = f"{abs(float(value)):.12g}"
                writer.writerow(
                    {
                        "code_a": target,
                        "name_a": names.get(target, ""),
                        "code_b": other,
                        "name_b": names.get(other, ""),
                        "correlation": correlation,
                        "abs_correlation": abs_correlation,
                        "sharpe_a": _format_optional_float(sharpe_by_code.get(target)),
                        "sharpe_b": _format_optional_float(sharpe_by_code.get(other)),
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

    return {
        "path": str(output_path),
        "fund_count": int(len(target_codes)),
        "source_fund_count": int(source_fund_count),
        "comparison_fund_count": int(len(codes)),
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
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _find_target_codes(query: str, codes: list[str], names: dict[str, str]) -> list[str]:
    q = str(query).strip().lower()
    if not q:
        return []
    exact = str(q).zfill(6) if q.isdigit() else q
    if exact in codes:
        return [exact]
    return [
        code
        for code in codes
        if q in code.lower() or q in names.get(code, "").lower()
    ]


def calculate_sharpe_by_code(returns: pd.DataFrame, *, periods_per_year: int = 252) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for code in returns.columns:
        series = pd.to_numeric(returns[code], errors="coerce").dropna()
        if len(series) < 2:
            result[str(code)] = None
            continue
        std = float(series.std())
        if not math.isfinite(std) or std <= 0:
            result[str(code)] = None
            continue
        mean = float(series.mean())
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
    value = changes.iloc[:, 0].corr(changes.iloc[:, 1])
    return (float(value), count) if _is_finite_number(value) else (None, count)


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
