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
  --output output/backtest_values.csv
```

The command writes portfolio values to `output/backtest_values.csv`.
It also writes an HTML report to `output/backtest_report.html`.
Fetched source data is cached in `data/fund_cache/`.

## Run from a portfolio config

```powershell
python -m fund_backtest.cli backtest --portfolio examples/portfolio.json
```

The config file can define `initial_cash`, `start`, `end`, `output`, `report`,
`cache_dir`, and a `funds` object mapping fund codes to weights.

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
