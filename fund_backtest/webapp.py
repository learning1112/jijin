from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pandas as pd

from .backtest import BacktestResult, normalize_weights, run_backtest


APP_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>基金回测系统</title>
  <style>
    :root {
      --bg: #f4f6f8;
      --panel: #ffffff;
      --ink: #19212a;
      --muted: #66717f;
      --line: #d8dee6;
      --accent: #247d8f;
      --accent-strong: #126276;
      --red: #bd3f45;
      --green: #2e7d5b;
      --yellow: #a66b00;
      --blue: #2f66b3;
      --soft: #edf4f6;
      --shadow: 0 1px 3px rgba(25, 33, 42, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Arial, "Microsoft YaHei", sans-serif;
      letter-spacing: 0;
    }
    button, input, select {
      font: inherit;
    }
    button {
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--ink);
      border-radius: 6px;
      cursor: pointer;
      min-height: 36px;
    }
    button:hover { border-color: var(--accent); }
    button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
      padding: 0 16px;
      font-weight: 700;
    }
    button.primary:hover { background: var(--accent-strong); }
    button.icon {
      width: 36px;
      min-width: 36px;
      padding: 0;
      font-size: 18px;
      line-height: 1;
    }
    input {
      width: 100%;
      height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 10px;
      background: #fff;
      color: var(--ink);
    }
    input[type="checkbox"] {
      width: 16px;
      height: 16px;
      accent-color: var(--accent);
    }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-rows: 58px 1fr;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 18px;
      background: #fff;
      border-bottom: 1px solid var(--line);
    }
    .brand {
      display: flex;
      align-items: baseline;
      gap: 12px;
      white-space: nowrap;
    }
    .brand h1 {
      margin: 0;
      font-size: 20px;
      letter-spacing: 0;
    }
    .status {
      min-width: 240px;
      color: var(--muted);
      font-size: 13px;
      text-align: right;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .workspace {
      display: grid;
      grid-template-columns: 360px minmax(0, 1fr);
      gap: 16px;
      padding: 16px;
      min-height: 0;
    }
    aside, section.panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    aside {
      padding: 16px;
      align-self: start;
      position: sticky;
      top: 74px;
    }
    main {
      display: grid;
      gap: 16px;
      align-content: start;
      min-width: 0;
    }
    .panel {
      padding: 16px;
      min-width: 0;
    }
    .panel h2, aside h2 {
      margin: 0 0 12px;
      font-size: 16px;
      letter-spacing: 0;
    }
    .form-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-bottom: 14px;
    }
    label {
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
    }
    label span {
      white-space: nowrap;
    }
    .fund-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 86px 36px;
      gap: 8px;
      margin-bottom: 8px;
      align-items: end;
    }
    .fund-head {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 86px 36px;
      gap: 8px;
      color: var(--muted);
      font-size: 12px;
      margin: 8px 0 6px;
    }
    .actions {
      display: flex;
      gap: 8px;
      margin-top: 14px;
    }
    .actions .primary { flex: 1; }
    .checkline {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 13px;
      margin-top: 2px;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(6, minmax(130px, 1fr));
      gap: 10px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fff;
      min-height: 82px;
    }
    .metric .name {
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 7px;
      white-space: nowrap;
    }
    .metric .value {
      font-size: 21px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }
    .charts {
      display: grid;
      grid-template-columns: minmax(0, 2fr) minmax(320px, 1fr);
      gap: 16px;
    }
    .chart-box {
      min-height: 310px;
    }
    .chart-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 13px;
    }
    canvas {
      display: block;
      width: 100%;
      height: 260px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th, td {
      padding: 10px 8px;
      border-bottom: 1px solid var(--line);
      text-align: right;
      white-space: nowrap;
    }
    th:first-child, td:first-child {
      text-align: left;
    }
    th {
      color: var(--muted);
      font-weight: 600;
      background: var(--soft);
    }
    .empty {
      min-height: 260px;
      border: 1px dashed var(--line);
      border-radius: 8px;
      display: grid;
      place-items: center;
      color: var(--muted);
      font-size: 14px;
    }
    .error {
      color: var(--red);
    }
    .ok {
      color: var(--green);
    }
    @media (max-width: 1100px) {
      .workspace, .charts {
        grid-template-columns: 1fr;
      }
      aside {
        position: static;
      }
      .metrics {
        grid-template-columns: repeat(3, minmax(130px, 1fr));
      }
    }
    @media (max-width: 640px) {
      header {
        display: grid;
        gap: 4px;
        height: auto;
        padding: 12px 14px;
      }
      .status {
        text-align: left;
        min-width: 0;
      }
      .workspace {
        padding: 10px;
      }
      .form-grid, .metrics {
        grid-template-columns: 1fr;
      }
      .fund-row, .fund-head {
        grid-template-columns: minmax(0, 1fr) 74px 36px;
      }
    }
  </style>
</head>
<body>
  <div class="app">
    <header>
      <div class="brand">
        <h1>基金回测系统</h1>
        <span id="rangeLabel" class="status">未运行</span>
      </div>
      <div id="status" class="status">就绪</div>
    </header>
    <div class="workspace">
      <aside>
        <h2>组合</h2>
        <div class="form-grid">
          <label><span>初始资金</span><input id="initialCash" type="number" min="1" step="100" value="10000"></label>
          <label><span>起始日期</span><input id="startDate" type="date" value="2021-01-01"></label>
          <label><span>结束日期</span><input id="endDate" type="date"></label>
          <label><span>缓存目录</span><input id="cacheDir" value="data/fund_cache"></label>
        </div>
        <div class="checkline"><input id="refresh" type="checkbox"><span>刷新天天基金数据</span></div>
        <div class="fund-head"><span>基金代码</span><span>权重</span><span></span></div>
        <div id="fundRows"></div>
        <div class="actions">
          <button class="icon" id="addFund" type="button" title="添加基金">+</button>
          <button class="primary" id="runBacktest" type="button">运行回测</button>
        </div>
      </aside>
      <main>
        <section class="panel">
          <h2>指标</h2>
          <div id="metrics" class="metrics"></div>
        </section>
        <div class="charts">
          <section class="panel chart-box">
            <div class="chart-title"><strong>资金曲线</strong><span id="valueScale"></span></div>
            <canvas id="valueChart" width="900" height="260"></canvas>
          </section>
          <section class="panel chart-box">
            <div class="chart-title"><strong>回撤</strong><span id="drawdownScale"></span></div>
            <canvas id="drawdownChart" width="520" height="260"></canvas>
          </section>
        </div>
        <section class="panel">
          <h2>持仓</h2>
          <div id="holdings"></div>
        </section>
      </main>
    </div>
  </div>

  <datalist id="fundSuggestions"></datalist>

  <script>
    const defaultFunds = [
      ["000307", 0.25],
      ["511010", 0.25],
      ["012693", 0.25],
      ["513110", 0.25]
    ];

    const state = { result: null };
    const $ = (id) => document.getElementById(id);

    function setStatus(message, kind = "") {
      const el = $("status");
      el.className = "status " + kind;
      el.textContent = message;
    }

    function addFundRow(code = "", weight = "") {
      const row = document.createElement("div");
      row.className = "fund-row";
      row.innerHTML = `
        <input class="fund-code" list="fundSuggestions" inputmode="numeric" maxlength="6" value="${code}">
        <input class="fund-weight" type="number" min="0" step="0.01" value="${weight}">
        <button class="icon remove-fund" type="button" title="删除基金">×</button>
      `;
      row.querySelector(".remove-fund").addEventListener("click", () => {
        row.remove();
        if (!document.querySelector(".fund-row")) addFundRow();
      });
      const codeInput = row.querySelector(".fund-code");
      codeInput.addEventListener("input", debounce(() => fetchFundSuggestions(codeInput.value), 220));
      $("fundRows").appendChild(row);
    }

    function debounce(fn, delay) {
      let timer;
      return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), delay);
      };
    }

    async function fetchFundSuggestions(query) {
      if (!query || query.length < 2) return;
      const response = await fetch(`/api/funds?q=${encodeURIComponent(query)}`);
      if (!response.ok) return;
      const payload = await response.json();
      const list = $("fundSuggestions");
      list.innerHTML = "";
      payload.items.forEach((item) => {
        const option = document.createElement("option");
        option.value = item.code;
        option.label = `${item.code} ${item.name} ${item.fund_type}`;
        list.appendChild(option);
      });
    }

    function readPayload() {
      const funds = [...document.querySelectorAll(".fund-row")].map((row) => ({
        code: row.querySelector(".fund-code").value.trim(),
        weight: Number(row.querySelector(".fund-weight").value)
      })).filter((item) => item.code && item.weight > 0);

      return {
        funds,
        initial_cash: Number($("initialCash").value),
        start: $("startDate").value || null,
        end: $("endDate").value || null,
        cache_dir: $("cacheDir").value || "data/fund_cache",
        refresh: $("refresh").checked
      };
    }

    async function runBacktest() {
      const payload = readPayload();
      if (!payload.funds.length) {
        setStatus("请至少填写一只基金", "error");
        return;
      }
      setStatus("回测中...");
      $("runBacktest").disabled = true;
      try {
        const response = await fetch("/api/backtest", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "回测失败");
        state.result = data;
        renderAll(data);
        setStatus("完成", "ok");
      } catch (error) {
        setStatus(error.message, "error");
      } finally {
        $("runBacktest").disabled = false;
      }
    }

    function renderAll(data) {
      $("rangeLabel").textContent = `${data.period.start} 至 ${data.period.end}`;
      renderMetrics(data.metrics);
      renderHoldings(data.final_holdings);
      drawLineChart("valueChart", data.series.map((row) => [row.date, row.total]), "#247d8f", "valueScale");
      drawLineChart("drawdownChart", data.series.map((row) => [row.date, row.drawdown * 100]), "#bd3f45", "drawdownScale", "%");
    }

    function renderMetrics(metrics) {
      const specs = [
        ["end_value", "期末资产", formatMoney],
        ["total_return", "总收益", formatPercent],
        ["annual_return", "年化收益", formatPercent],
        ["max_drawdown", "最大回撤", formatPercent],
        ["volatility", "波动率", formatPercent],
        ["sharpe", "Sharpe", (v) => Number(v).toFixed(3)]
      ];
      $("metrics").innerHTML = specs.map(([key, name, formatter]) => `
        <div class="metric">
          <div class="name">${name}</div>
          <div class="value">${formatter(metrics[key] ?? 0)}</div>
        </div>
      `).join("");
    }

    function renderHoldings(rows) {
      if (!rows.length) {
        $("holdings").innerHTML = `<div class="empty">暂无持仓</div>`;
        return;
      }
      $("holdings").innerHTML = `
        <table>
          <thead><tr><th>基金</th><th>目标权重</th><th>期末资产</th><th>实际权重</th></tr></thead>
          <tbody>
            ${rows.map((row) => `
              <tr>
                <td>${escapeHtml(row.code)}</td>
                <td>${formatPercent(row.target_weight)}</td>
                <td>${formatMoney(row.final_value)}</td>
                <td>${formatPercent(row.actual_weight)}</td>
              </tr>`).join("")}
          </tbody>
        </table>
      `;
    }

    function drawLineChart(canvasId, rows, color, scaleId, suffix = "") {
      const canvas = $(canvasId);
      const ctx = canvas.getContext("2d");
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.max(1, Math.floor(rect.width * dpr));
      canvas.height = Math.max(1, Math.floor(rect.height * dpr));
      ctx.scale(dpr, dpr);
      const width = rect.width;
      const height = rect.height;
      ctx.clearRect(0, 0, width, height);

      if (!rows.length) return;
      const values = rows.map((row) => row[1]).filter((value) => Number.isFinite(value));
      let min = Math.min(...values);
      let max = Math.max(...values);
      if (min === max) { min -= 1; max += 1; }

      const pad = { left: 58, right: 16, top: 16, bottom: 34 };
      const cw = width - pad.left - pad.right;
      const ch = height - pad.top - pad.bottom;
      ctx.strokeStyle = "#d8dee6";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(pad.left, pad.top);
      ctx.lineTo(pad.left, pad.top + ch);
      ctx.lineTo(pad.left + cw, pad.top + ch);
      ctx.stroke();

      ctx.fillStyle = "#66717f";
      ctx.font = "12px Arial";
      ctx.fillText(formatAxis(max, suffix), 8, pad.top + 5);
      ctx.fillText(formatAxis(min, suffix), 8, pad.top + ch);
      ctx.fillText(rows[0][0], pad.left, height - 10);
      const lastLabel = rows[rows.length - 1][0];
      const labelWidth = ctx.measureText(lastLabel).width;
      ctx.fillText(lastLabel, width - pad.right - labelWidth, height - 10);

      ctx.strokeStyle = color;
      ctx.lineWidth = 2.3;
      ctx.beginPath();
      rows.forEach((row, index) => {
        const x = pad.left + (index / Math.max(rows.length - 1, 1)) * cw;
        const y = pad.top + (1 - ((row[1] - min) / (max - min))) * ch;
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
      $(scaleId).textContent = `${formatAxis(min, suffix)} / ${formatAxis(max, suffix)}`;
    }

    function formatMoney(value) {
      return Number(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    function formatPercent(value) {
      return `${(Number(value) * 100).toFixed(2)}%`;
    }
    function formatAxis(value, suffix) {
      if (suffix === "%") return `${Number(value).toFixed(1)}%`;
      return Math.abs(value) >= 100 ? Number(value).toFixed(0) : Number(value).toFixed(2);
    }
    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[char]));
    }

    $("addFund").addEventListener("click", () => addFundRow());
    $("runBacktest").addEventListener("click", runBacktest);
    window.addEventListener("resize", () => state.result && renderAll(state.result));
    defaultFunds.forEach(([code, weight]) => addFundRow(code, weight));
    renderMetrics({});
    $("holdings").innerHTML = `<div class="empty">暂无持仓</div>`;
  </script>
</body>
</html>
"""


class BacktestRequestHandler(BaseHTTPRequestHandler):
    server_version = "FundBacktestHTTP/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._send_bytes(APP_HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/funds":
            params = parse_qs(parsed.query)
            query = params.get("q", [""])[0]
            items = search_funds(query, limit=20)
            self._send_json({"items": items})
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/backtest":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._read_json()
            result = run_backtest_payload(payload)
            self._send_json(result)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[web] {self.address_string()} - {format % args}")

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length)
        if not data:
            return {}
        payload = json.loads(data.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON payload must be an object.")
        return payload

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send_bytes(
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            status=status,
        )

    def _send_bytes(
        self,
        payload: bytes,
        content_type: str | None = None,
        *,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def run_backtest_payload(payload: dict[str, Any]) -> dict[str, Any]:
    weights = _weights_from_payload(payload)
    initial_cash = float(payload.get("initial_cash") or 10000.0)
    if initial_cash <= 0:
        raise ValueError("Initial cash must be positive.")

    result = run_backtest(
        weights,
        initial_cash=initial_cash,
        start=_blank_to_none(payload.get("start")),
        end=_blank_to_none(payload.get("end")),
        cache_dir=str(payload.get("cache_dir") or "data/fund_cache"),
        refresh=bool(payload.get("refresh", False)),
    )
    return serialize_backtest_result(result, weights)


def serialize_backtest_result(
    result: BacktestResult,
    weights: dict[str, float],
    *,
    max_points: int = 1200,
) -> dict[str, Any]:
    values = result.values.copy()
    sampled = _downsample_frame(values, max_points=max_points)
    normalized = normalize_weights(weights)
    final = values.iloc[-1]
    total = float(final["total"])
    holdings = []
    for code, target_weight in sorted(normalized.items()):
        if code not in values.columns:
            continue
        amount = float(final[code])
        holdings.append(
            {
                "code": code,
                "target_weight": target_weight,
                "final_value": amount,
                "actual_weight": amount / total if total else 0.0,
            }
        )
    return {
        "period": {
            "start": values.index.min().strftime("%Y-%m-%d"),
            "end": values.index.max().strftime("%Y-%m-%d"),
        },
        "metrics": result.metrics,
        "weights": normalized,
        "final_holdings": holdings,
        "series": [
            {
                "date": index.strftime("%Y-%m-%d"),
                "total": float(row["total"]),
                "drawdown": float(row["drawdown"]),
            }
            for index, row in sampled.iterrows()
        ],
    }


def search_funds(query: str, *, limit: int = 20) -> list[dict[str, str]]:
    catalog = load_fund_catalog()
    if catalog.empty:
        return []
    q = str(query).strip().lower()
    if q:
        mask = (
            catalog["code"].str.lower().str.contains(q, na=False)
            | catalog["name"].str.lower().str.contains(q, na=False)
            | catalog["fund_type"].str.lower().str.contains(q, na=False)
            | catalog["pinyin"].str.lower().str.contains(q, na=False)
        )
        catalog = catalog.loc[mask]
    return catalog.head(limit).to_dict(orient="records")


def load_fund_catalog() -> pd.DataFrame:
    candidates = [Path("data/fund_codes.csv"), Path("基金列表.csv")]
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
        if "code" not in frame.columns:
            continue
        for column in ["name", "fund_type", "pinyin"]:
            if column not in frame.columns:
                frame[column] = ""
        frame["code"] = frame["code"].astype(str).str.zfill(6)
        return frame[["code", "name", "fund_type", "pinyin"]]
    return pd.DataFrame(columns=["code", "name", "fund_type", "pinyin"])


def run_server(host: str = "127.0.0.1", port: int = 8000, *, open_browser: bool = False) -> None:
    server = ThreadingHTTPServer((host, port), BacktestRequestHandler)
    url = f"http://{host}:{port}/"
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    print(f"Fund backtest UI running at {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down")
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fund-backtest-web")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--open", action="store_true", help="Open the UI in the default browser.")
    args = parser.parse_args(argv)
    run_server(args.host, args.port, open_browser=args.open)
    return 0


def _weights_from_payload(payload: dict[str, Any]) -> dict[str, float]:
    funds = payload.get("funds")
    if isinstance(funds, dict):
        return {str(code).zfill(6): float(weight) for code, weight in funds.items()}
    if isinstance(funds, list):
        weights: dict[str, float] = {}
        for item in funds:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code", "")).strip().zfill(6)
            weight = float(item.get("weight") or 0)
            if code and weight > 0:
                weights[code] = weight
        if weights:
            return weights
    raise ValueError("Provide at least one fund with a positive weight.")


def _blank_to_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _downsample_frame(frame: pd.DataFrame, *, max_points: int) -> pd.DataFrame:
    if len(frame) <= max_points:
        return frame
    step = max(len(frame) // max_points, 1)
    sampled = frame.iloc[::step]
    if sampled.index[-1] != frame.index[-1]:
        sampled = pd.concat([sampled, frame.iloc[[-1]]])
    return sampled


if __name__ == "__main__":
    raise SystemExit(main())
