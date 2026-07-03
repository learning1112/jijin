# Fund Backtest MVP

This project now has a small reusable backtesting core under `fund_backtest/`.
It keeps the original exploration scripts intact and adds:

- Eastmoney/Tiantian Fund public data client
- CSV cache for fetched fund series
- Portfolio backtest engine
- Metrics: total return, annualized return, max drawdown, volatility, Sharpe
- CLI entry point

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
Fetched source data is cached in `data/fund_cache/`.

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
