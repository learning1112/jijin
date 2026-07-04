from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Mapping

import pandas as pd

from .backtest import BacktestResult, normalize_weights


METRIC_LABELS = {
    "start_value": "Start value",
    "end_value": "End value",
    "total_return": "Total return",
    "annual_return": "Annual return",
    "max_drawdown": "Max drawdown",
    "volatility": "Volatility",
    "sharpe": "Sharpe",
    "elapsed_days": "Elapsed days",
    "total_fees": "Total fees",
    "rebalance_count": "Rebalances",
    "average_turnover": "Average turnover",
    "total_contributions": "Total contributions",
    "net_profit": "Net profit",
    "return_on_contributions": "Return on contributions",
}


def save_html_report(
    result: BacktestResult,
    weights: Mapping[str, float],
    path: str | Path,
    *,
    title: str = "Fund Backtest Report",
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_html_report(result, weights, title=title),
        encoding="utf-8",
    )
    return output_path


def render_html_report(
    result: BacktestResult,
    weights: Mapping[str, float],
    *,
    title: str = "Fund Backtest Report",
) -> str:
    values = result.values.copy()
    if values.empty:
        raise ValueError("Cannot render a report for an empty backtest result.")

    normalized_weights = normalize_weights(weights)
    start_date = values.index.min().strftime("%Y-%m-%d")
    end_date = values.index.max().strftime("%Y-%m-%d")
    generated_at = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    settings = _render_settings(result)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #1f2933;
      --muted: #687482;
      --line: #d8dee6;
      --accent: #1f7a8c;
      --danger: #b23a48;
      --soft: #eef6f8;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Arial, "Microsoft YaHei", sans-serif;
      line-height: 1.45;
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }}
    header {{
      display: flex;
      justify-content: space-between;
      gap: 24px;
      align-items: flex-end;
      margin-bottom: 24px;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 32px;
      letter-spacing: 0;
    }}
    h2 {{
      margin: 0 0 14px;
      font-size: 20px;
      letter-spacing: 0;
    }}
    .muted {{
      color: var(--muted);
      font-size: 14px;
    }}
    .grid {{
      display: grid;
      gap: 16px;
    }}
    .metrics {{
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      margin-bottom: 20px;
    }}
    .metric, section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 1px 2px rgba(31, 41, 51, 0.04);
    }}
    .metric {{
      padding: 16px;
    }}
    .metric .label {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 8px;
    }}
    .metric .value {{
      font-size: 24px;
      font-weight: 700;
    }}
    section {{
      padding: 20px;
      margin-bottom: 20px;
    }}
    .two-col {{
      grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr);
      align-items: start;
    }}
    svg {{
      width: 100%;
      height: auto;
      display: block;
      overflow: visible;
    }}
    .axis {{
      stroke: var(--line);
      stroke-width: 1;
    }}
    .portfolio-line {{
      fill: none;
      stroke: var(--accent);
      stroke-width: 2.4;
    }}
    .drawdown-line {{
      fill: none;
      stroke: var(--danger);
      stroke-width: 2.2;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 8px;
      text-align: right;
    }}
    th:first-child, td:first-child {{
      text-align: left;
    }}
    th {{
      color: var(--muted);
      font-weight: 600;
      background: var(--soft);
    }}
    @media (max-width: 800px) {{
      header, .two-col {{
        display: block;
      }}
      h1 {{
        font-size: 26px;
      }}
      section {{
        padding: 16px;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>{escape(title)}</h1>
        <div class="muted">Period: {start_date} to {end_date}</div>
      </div>
      <div class="muted">Generated: {generated_at}</div>
    </header>

    <div class="grid metrics">
      {_render_metric_cards(result.metrics)}
    </div>

    {_render_annual_metrics_table(result.annual_metrics)}

    {settings}

    <div class="grid two-col">
      <section>
        <h2>Portfolio Value</h2>
        {_render_line_chart(values["total"], css_class="portfolio-line")}
      </section>
      <section>
        <h2>Weights</h2>
        {_render_weights_table(normalized_weights)}
      </section>
    </div>

    <section>
      <h2>Drawdown</h2>
      {_render_line_chart(values["drawdown"] * 100.0, css_class="drawdown-line", y_suffix="%")}
    </section>

    <section>
      <h2>Final Holdings</h2>
      {_render_final_holdings(values, normalized_weights)}
    </section>
  </main>
</body>
</html>
"""


def _render_metric_cards(metrics: Mapping[str, float]) -> str:
    preferred = [
        "end_value",
        "total_return",
        "annual_return",
        "max_drawdown",
        "volatility",
        "sharpe",
        "total_contributions",
        "net_profit",
        "return_on_contributions",
        "total_fees",
        "rebalance_count",
        "elapsed_days",
    ]
    return "\n".join(
        f"""<div class="metric">
        <div class="label">{escape(METRIC_LABELS.get(key, key))}</div>
        <div class="value">{escape(_format_metric(key, metrics[key]))}</div>
      </div>"""
        for key in preferred
        if key in metrics
    )


def _render_weights_table(weights: Mapping[str, float]) -> str:
    rows = "\n".join(
        f"<tr><td>{escape(code)}</td><td>{weight:.2%}</td></tr>"
        for code, weight in sorted(weights.items())
    )
    return f"""<table>
      <thead><tr><th>Fund</th><th>Weight</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


def _render_annual_metrics_table(rows: list[dict[str, float]]) -> str:
    if not rows:
        return ""
    body = "".join(
        "<tr>"
        f"<td>{int(row['year'])}</td>"
        f"<td>{_format_metric('end_value', row['end_value'])}</td>"
        f"<td>{_format_metric('total_return', row['total_return'])}</td>"
        f"<td>{_format_metric('max_drawdown', row['max_drawdown'])}</td>"
        f"<td>{_format_metric('total_contributions', row['total_contributions'])}</td>"
        f"<td>{_format_metric('net_profit', row['net_profit'])}</td>"
        f"<td>{_format_metric('return_on_contributions', row['return_on_contributions'])}</td>"
        f"<td>{_format_metric('total_fees', row['total_fees'])}</td>"
        f"<td>{_format_metric('rebalance_count', row['rebalance_count'])}</td>"
        "</tr>"
        for row in rows
    )
    return f"""<section>
      <h2>Annual Metrics</h2>
      <table>
        <thead>
          <tr>
            <th>Year</th>
            <th>End value</th>
            <th>Return</th>
            <th>Max drawdown</th>
            <th>Contributions</th>
            <th>Net profit</th>
            <th>Contribution return</th>
            <th>Fees</th>
            <th>Rebalances</th>
          </tr>
        </thead>
        <tbody>{body}</tbody>
      </table>
    </section>"""


def _render_settings(result: BacktestResult) -> str:
    if not result.metadata:
        return ""
    frequency = str(result.metadata.get("rebalance_frequency", "none"))
    fee_rate = float(result.metadata.get("fee_rate", 0.0))
    contribution_amount = float(result.metadata.get("contribution_amount", 0.0))
    contribution_frequency = str(result.metadata.get("contribution_frequency", "none"))
    contribution_weekday = str(result.metadata.get("contribution_weekday", "monday"))
    return f"""<section>
      <h2>Settings</h2>
      <table>
        <tbody>
          <tr><td>Rebalance frequency</td><td>{escape(frequency)}</td></tr>
          <tr><td>Trade fee rate</td><td>{fee_rate:.3%}</td></tr>
          <tr><td>Regular contribution</td><td>{contribution_amount:,.2f}</td></tr>
          <tr><td>Contribution frequency</td><td>{escape(contribution_frequency)}</td></tr>
          <tr><td>Contribution weekday</td><td>{escape(contribution_weekday)}</td></tr>
        </tbody>
      </table>
    </section>"""


def _render_final_holdings(values: pd.DataFrame, weights: Mapping[str, float]) -> str:
    final = values.iloc[-1]
    total = float(final["total"])
    rows = []
    for code in sorted(weights):
        if code not in values.columns:
            continue
        amount = float(final[code])
        actual_weight = amount / total if total else 0.0
        rows.append(
            f"<tr><td>{escape(code)}</td><td>{amount:,.2f}</td><td>{actual_weight:.2%}</td></tr>"
        )
    return f"""<table>
      <thead><tr><th>Fund</th><th>Final value</th><th>Actual weight</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>"""


def _render_line_chart(
    series: pd.Series,
    *,
    css_class: str,
    y_suffix: str = "",
    width: int = 900,
    height: int = 300,
) -> str:
    clean = series.dropna()
    if clean.empty:
        return '<div class="muted">No data</div>'

    sampled = _downsample(clean, max_points=800)
    padding_left = 62
    padding_right = 16
    padding_top = 18
    padding_bottom = 36
    chart_width = width - padding_left - padding_right
    chart_height = height - padding_top - padding_bottom
    y_min = float(sampled.min())
    y_max = float(sampled.max())
    if y_min == y_max:
        y_min -= 1.0
        y_max += 1.0

    points = []
    count = len(sampled)
    for index, value in enumerate(sampled):
        x = padding_left + (index / max(count - 1, 1)) * chart_width
        y = padding_top + (1 - ((float(value) - y_min) / (y_max - y_min))) * chart_height
        points.append(f"{x:.2f},{y:.2f}")

    start_label = sampled.index.min().strftime("%Y-%m-%d")
    end_label = sampled.index.max().strftime("%Y-%m-%d")
    y_low = _format_axis_value(y_min, y_suffix)
    y_high = _format_axis_value(y_max, y_suffix)

    return f"""<svg viewBox="0 0 {width} {height}" role="img" aria-label="Line chart">
      <line class="axis" x1="{padding_left}" y1="{padding_top}" x2="{padding_left}" y2="{height - padding_bottom}" />
      <line class="axis" x1="{padding_left}" y1="{height - padding_bottom}" x2="{width - padding_right}" y2="{height - padding_bottom}" />
      <text x="8" y="{padding_top + 5}" font-size="12" fill="#687482">{escape(y_high)}</text>
      <text x="8" y="{height - padding_bottom}" font-size="12" fill="#687482">{escape(y_low)}</text>
      <text x="{padding_left}" y="{height - 10}" font-size="12" fill="#687482">{escape(start_label)}</text>
      <text x="{width - padding_right}" y="{height - 10}" font-size="12" fill="#687482" text-anchor="end">{escape(end_label)}</text>
      <polyline class="{escape(css_class)}" points="{' '.join(points)}" />
    </svg>"""


def _downsample(series: pd.Series, max_points: int) -> pd.Series:
    if len(series) <= max_points:
        return series
    step = max(len(series) // max_points, 1)
    sampled = series.iloc[::step]
    if sampled.index[-1] != series.index[-1]:
        sampled = pd.concat([sampled, series.iloc[[-1]]])
    return sampled


def _format_metric(key: str, value: float) -> str:
    if key in {
        "total_return",
        "annual_return",
        "max_drawdown",
        "volatility",
        "average_turnover",
        "return_on_contributions",
    }:
        return f"{value:.2%}"
    if key in {"start_value", "end_value", "total_fees", "total_contributions", "net_profit"}:
        return f"{value:,.2f}"
    if key in {"elapsed_days", "rebalance_count"}:
        return f"{value:,.0f}"
    return f"{value:.3f}"


def _format_axis_value(value: float, suffix: str) -> str:
    if suffix == "%":
        return f"{value:.1f}%"
    return f"{value:,.0f}" if abs(value) >= 100 else f"{value:.2f}"
