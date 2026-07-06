from __future__ import annotations

from pathlib import Path

import pandas as pd

from .eastmoney import FundSeries, HistoryType


class CsvFundCache:
    def __init__(self, root: str | Path = "data/fund_cache") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def load(self, code: str) -> FundSeries | None:
        path = self.path_for(code)
        if not path.exists():
            return None
        frame = pd.read_csv(path, parse_dates=["date"])
        if frame.empty:
            return None
        data_type = str(frame["data_type"].iloc[0])
        values = frame[["date", "value"]].set_index("date").sort_index()
        return FundSeries(code=str(code).zfill(6), data_type=data_type, frame=values)  # type: ignore[arg-type]

    def save(self, series: FundSeries) -> Path:
        path = self.path_for(series.code)
        frame = series.frame.copy()
        frame.index.name = "date"
        frame = frame.reset_index()
        frame["data_type"] = series.data_type
        frame.to_csv(path, index=False, encoding="utf-8")
        return path

    def get_or_fetch(self, code: str, client, refresh: bool = False) -> FundSeries:
        if not refresh:
            cached = self.load(code)
            if cached is not None:
                return cached
        series = client.fetch_history(code)
        self.save(series)
        return series

    def path_for(self, code: str) -> Path:
        return self.root / f"{str(code).zfill(6)}.csv"
