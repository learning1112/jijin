# Fund Backtest MVP

This project now has a small reusable backtesting core under `fund_backtest/`.
It keeps the original exploration scripts intact and adds:

- Eastmoney/Tiantian Fund public data client
- CSV cache for fetched fund series
- Portfolio backtest engine
- Metrics: total return, annualized return, max drawdown, volatility, Sharpe
- CLI entry point
- HTML report with portfolio value, drawdown, weights, and final holdings
- Local visual web UI
- Rebalancing frequency and trade fee assumptions
- Regular contribution / dollar-cost averaging mode
- Daily regular contribution on every available trading day
- Weekly regular contribution weekday selection from Monday to Friday
- Fund universe screening by actual 5-year or 10-year history coverage
- Annual metrics table in the visual UI and HTML reports

For non-money-market funds, the Eastmoney parser prefers `Data_ACWorthTrend`,
which is the accumulated net-worth trend. If that series is unavailable it falls
back to `Data_netWorthTrend`. Money-market funds use `Data_millionCopiesIncome`.

## Start the visual UI

```powershell
python -m fund_backtest.cli web --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000/`.

## Create the Conda environment

```powershell
conda env create -f environment.yml
conda activate jijin-backtest
```

If the environment already exists:

```powershell
conda env update -f environment.yml --prune
conda activate jijin-backtest
```

## Run a backtest

```powershell
python -m fund_backtest.cli backtest `
  --fund 000307=0.25 `
  --fund 511010=0.25 `
  --fund 012693=0.25 `
  --fund 513110=0.25 `
  --start 2021-01-01 `
  --rebalance-frequency monthly `
  --fee-rate 0.001 `
  --contribution-amount 1000 `
  --contribution-frequency weekly `
  --contribution-weekday wednesday `
  --output output/backtest_values.csv
```

The command writes portfolio values to `output/backtest_values.csv`.
It also writes an HTML report to `output/backtest_report.html`.
Fetched source data is cached in `data/fund_cache/`.

## Run from a portfolio config

```powershell
python -m fund_backtest.cli backtest --portfolio examples/portfolio.json
```

The config file can define `initial_cash`, `start`, `end`, `rebalance_frequency`,
`fee_rate`, `contribution_amount`, `contribution_frequency`,
`contribution_weekday`, `min_history_years`, `coverage`, `max_stale_days`,
`output`, `report`, `cache_dir`, and a `funds` object mapping fund codes to
weights.

## Build a 5-year or 10-year fund universe

The history filter uses each fund's actual fetched net-worth series. It checks
the first and latest available data dates instead of relying on the fund catalog.

```powershell
python -m fund_backtest.cli screen-funds `
  --min-history-years 5 `
  --as-of 2026-07-04 `
  --output data/fund_universe_5y.csv
```

For a 10-year universe:

```powershell
python -m fund_backtest.cli screen-funds `
  --min-history-years 10 `
  --as-of 2026-07-04 `
  --output data/fund_universe_10y.csv
```

The command maintains `data/fund_coverage.csv` as a reusable coverage index, so
interrupted scans can continue without refetching completed rows. By default,
funds whose latest data is more than 45 days older than the reference date are
excluded. Use `--refresh` to refetch histories.

The web UI can filter fund search suggestions by 不限, ≥5年, or ≥10年. If the
coverage index has not been created yet, it will show unfiltered suggestions and
ask you to run `screen-funds` first. Backtests still validate selected funds when
a minimum history filter is enabled.

## Run a regular-contribution backtest

```powershell
python -m fund_backtest.cli backtest --portfolio examples/dca_portfolio.json
```

Monthly, quarterly, and yearly regular contributions are invested on the first
available trading day in each selected period, including the first backtest date.
Daily regular contributions are invested on every available trading day.
Weekly regular contributions can choose `monday` through `friday`; if that day
has no fund data, the contribution is invested on the next available trading day
in the same week.

## Refresh source data

```powershell
python -m fund_backtest.cli backtest --refresh --fund 000307=1
```

## Download the fund list

```powershell
python -m fund_backtest.cli fund-codes --output data/fund_codes.csv
```

## Run tests

```powershell
python -m unittest discover -s tests
```
