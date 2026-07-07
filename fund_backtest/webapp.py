from __future__ import annotations

import argparse
import json
import math
import threading
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pandas as pd

from .backtest import BacktestResult, normalize_weights, run_backtest
from .correlation import compute_correlation_index, load_correlation_payload
from .data_management import build_coverage_index, get_data_status, refresh_fund_catalog, refresh_purchase_status
from .purchase_status import DEFAULT_PURCHASE_STATUS_PATH, attach_purchase_status_fields, filter_purchase_availability
from .screening import (
    DEFAULT_COVERAGE_PATH,
    DEFAULT_MAX_STALE_DAYS,
    filter_coverage,
    load_coverage_index,
    load_fund_catalog as load_screening_fund_catalog,
    validate_fund_history_requirement,
)


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
    input, select {
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
      align-self: start;
      position: sticky;
      top: 74px;
      display: grid;
      grid-template-rows: minmax(0, 1fr) auto;
      max-height: calc(100vh - 90px);
      overflow: hidden;
    }
    .portfolio-scroll {
      min-height: 0;
      overflow-y: auto;
      padding: 16px;
      scrollbar-gutter: stable;
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
      align-items: start;
    }
    .fund-meta {
      grid-column: 1 / -1;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
      min-height: 34px;
      padding: 0 2px;
      overflow-wrap: anywhere;
      white-space: normal;
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
      margin: 0;
      padding: 10px 16px 16px;
      border-top: 1px solid var(--line);
      background: var(--panel);
    }
    .actions .primary { flex: 1; }
    .section-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }
    .section-head h2 {
      margin: 0;
    }
    .inline-status {
      color: var(--muted);
      font-size: 13px;
      text-align: right;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .tool-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(130px, 1fr));
      gap: 10px;
      align-items: end;
      margin-bottom: 12px;
    }
    .tool-grid button {
      padding: 0 12px;
      font-weight: 600;
    }
    .job-status {
      min-height: 32px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      color: var(--muted);
      font-size: 13px;
      background: #fff;
      overflow-wrap: anywhere;
    }
    .pager {
      display: flex;
      justify-content: flex-end;
      align-items: center;
      gap: 8px;
      margin-top: 10px;
      color: var(--muted);
      font-size: 13px;
    }
    .pager button {
      min-height: 30px;
      padding: 0 10px;
      font-size: 12px;
    }
    .pager button:disabled {
      cursor: default;
      opacity: 0.45;
    }
    .table-scroll {
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
    }
    .table-scroll table th,
    .table-scroll table td {
      font-size: 12px;
    }
    .correlation-table {
      min-height: 360px;
    }
    .fund-cell {
      display: grid;
      gap: 3px;
      min-width: 190px;
      line-height: 1.35;
      white-space: normal;
    }
    .fund-code-text {
      color: var(--ink);
      font-weight: 600;
    }
    .fund-name-text {
      color: var(--ink);
    }
    .fund-type-text {
      color: var(--muted);
      font-size: 11px;
    }
    .purchase-badge {
      display: inline-flex;
      align-items: center;
      min-height: 20px;
      padding: 0 7px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 700;
      white-space: nowrap;
    }
    .purchase-open {
      background: #e8f4ef;
      color: var(--green);
    }
    .purchase-limited {
      background: #fff4df;
      color: var(--yellow);
    }
    .purchase-closed {
      background: #f9e8ea;
      color: var(--red);
    }
    .purchase-unknown {
      background: #eef2f6;
      color: var(--muted);
    }
    .sort-icon {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 20px;
      height: 20px;
      margin-left: 6px;
      padding: 0;
      border: 1px solid var(--line);
      border-radius: 4px;
      background: #f5f7fa;
      color: var(--muted);
      font-size: 12px;
      line-height: 1;
      cursor: pointer;
      vertical-align: middle;
      transition: background 0.15s, color 0.15s, border-color 0.15s;
    }
    .sort-icon:hover {
      background: #eaf1fb;
      color: #2563eb;
      border-color: #c7d7ee;
    }
    .sort-icon.is-active {
      background: #2563eb;
      border-color: #2563eb;
      color: #fff;
    }
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
      gap: 10px;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 13px;
    }
    .chart-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }
    .chart-actions span {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .chart-reset {
      min-height: 28px;
      padding: 0 10px;
      font-size: 12px;
    }
    canvas {
      display: block;
      width: 100%;
      height: 260px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      cursor: crosshair;
      user-select: none;
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
      .tool-grid {
        grid-template-columns: 1fr;
      }
      aside {
        position: static;
        top: auto;
        max-height: calc(100vh - 20px);
      }
      .portfolio-scroll {
        overflow-y: auto;
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
      .actions {
        padding: 10px 16px 16px;
      }
      .chart-title {
        align-items: flex-start;
        display: grid;
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
        <div class="portfolio-scroll">
          <h2>组合</h2>
          <div class="form-grid">
            <label><span>初始资金</span><input id="initialCash" type="number" min="1" step="100" value="10000"></label>
            <label><span>起始日期</span><input id="startDate" type="date" value="2021-01-01"></label>
            <label><span>结束日期</span><input id="endDate" type="date"></label>
            <label><span>历史数据年限</span><select id="minHistoryYears">
              <option value="0" selected>不限</option>
              <option value="5">≥5年</option>
              <option value="10">≥10年</option>
            </select></label>
            <label><span>再平衡</span><select id="rebalanceFrequency">
              <option value="none">不再平衡</option>
              <option value="monthly">每月</option>
              <option value="quarterly">每季度</option>
              <option value="yearly">每年</option>
            </select></label>
            <label><span>交易费率</span><input id="feeRate" type="number" min="0" step="0.0001" value="0"></label>
            <label><span>定投金额</span><input id="contributionAmount" type="number" min="0" step="100" value="0"></label>
            <label><span>定投频率</span><select id="contributionFrequency">
              <option value="none">不定投</option>
              <option value="daily">每个交易日</option>
              <option value="weekly">每周</option>
              <option value="monthly" selected>每月</option>
              <option value="quarterly">每季度</option>
              <option value="yearly">每年</option>
            </select></label>
            <label id="contributionWeekdayLabel"><span>定投星期</span><select id="contributionWeekday">
              <option value="monday" selected>周一</option>
              <option value="tuesday">周二</option>
              <option value="wednesday">周三</option>
              <option value="thursday">周四</option>
              <option value="friday">周五</option>
            </select></label>
            <label><span>缓存目录</span><input id="cacheDir" value="data/fund_cache"></label>
          </div>
          <div class="checkline"><input id="refresh" type="checkbox"><span>刷新天天基金数据</span></div>
          <div class="fund-head"><span>基金代码</span><span>权重</span><span></span></div>
          <div id="fundRows"></div>
        </div>
        <div class="actions">
          <button class="icon" id="addFund" type="button" title="添加基金">+</button>
          <button class="primary" id="runBacktest" type="button">运行回测</button>
        </div>
      </aside>
      <main>
        <section class="panel">
          <div class="section-head">
            <h2>数据管理</h2>
            <span id="dataStatus" class="inline-status">读取中</span>
          </div>
          <div class="tool-grid">
            <button id="refreshCatalog" type="button">更新基金列表</button>
            <label><span>覆盖截至日期</span><input id="coverageAsOf" type="date"></label>
            <label class="checkline"><input id="coverageRefresh" type="checkbox"><span>重抓历史数据</span></label>
            <button class="primary" id="buildCoverage" type="button">生成覆盖索引</button>
            <button id="refreshPurchaseStatus" type="button">更新申购状态</button>
          </div>
          <div id="dataJobStatus" class="job-status">就绪</div>
        </section>
        <section class="panel">
          <h2>指标</h2>
          <div id="metrics" class="metrics"></div>
        </section>
        <section class="panel">
          <h2>年度指标</h2>
          <div id="annualMetrics"></div>
        </section>
        <div class="charts">
          <section class="panel chart-box">
            <div class="chart-title">
              <strong>资金曲线</strong>
              <div class="chart-actions">
                <span id="valueScale"></span>
                <button class="chart-reset" id="resetValueChart" type="button">重置</button>
              </div>
            </div>
            <canvas id="valueChart" width="900" height="260"></canvas>
          </section>
          <section class="panel chart-box">
            <div class="chart-title">
              <strong>回撤</strong>
              <div class="chart-actions">
                <span id="drawdownScale"></span>
                <button class="chart-reset" id="resetDrawdownChart" type="button">重置</button>
              </div>
            </div>
            <canvas id="drawdownChart" width="520" height="260"></canvas>
          </section>
        </div>
        <section class="panel">
          <div class="section-head">
            <h2>相关性分析</h2>
            <span id="correlationSummary" class="inline-status">暂无数据</span>
          </div>
          <div class="tool-grid">
            <label><span>最小年限</span><select id="corrMinHistoryYears">
              <option value="5" selected>≥5年</option>
              <option value="10">≥10年</option>
            </select></label>
            <label><span>截至日期</span><input id="corrAsOf" type="date"></label>
            <label><span>基金A</span><input id="corrQueryA" placeholder="代码或名称"></label>
            <label><span>基金B</span><input id="corrQueryB" placeholder="代码或名称"></label>
            <label><span>排序</span><select id="corrSort">
              <option value="abs_desc" selected>相关强度（强→弱）</option>
              <option value="abs_asc">弱相关优先</option>
              <option value="corr_desc">正相关（高→低）</option>
              <option value="corr_asc">负相关（低→高）</option>
              <option value="sharpe_b_desc">Sharpe高</option>
              <option value="sharpe_b_asc">Sharpe低</option>
            </select></label>
            <label><span>相关性区间</span><select id="corrRange">
              <option value="all" selected>全部</option>
              <option value="strong_neg">强负相关 (&lt; -0.7)</option>
              <option value="mid_neg">中负相关 (-0.7 ~ -0.3)</option>
              <option value="weak">低相关 (-0.3 ~ 0.3)</option>
              <option value="mid_pos">中正相关 (0.3 ~ 0.7)</option>
              <option value="strong_pos">强正相关 (&gt; 0.7)</option>
            </select></label>
            <label><span>Sharpe 区间</span><select id="sharpeRange">
              <option value="all" selected>全部</option>
              <option value="lt0">&lt; 0</option>
              <option value="0_1">0 ~ 1</option>
              <option value="1_2">1 ~ 2</option>
              <option value="2_3">2 ~ 3</option>
              <option value="gt3">≥ 3</option>
            </select></label>
            <label><span>B购买状态</span><select id="corrPurchaseAvailability">
              <option value="all" selected>全部</option>
              <option value="tradable">B可买含限额</option>
              <option value="open">B可购买</option>
              <option value="limited">B限额</option>
              <option value="closed">B不可购买</option>
              <option value="unknown">B未知</option>
            </select></label>
            <label><span>每页</span><select id="corrPageSize">
              <option value="10" selected>10</option>
              <option value="50">50</option>
              <option value="100">100</option>
              <option value="200">200</option>
              <option value="500">500</option>
            </select></label>
            <button class="primary" id="computeCorrelation" type="button">计算相关性</button>
            <button id="refreshCorrelation" type="button">刷新结果</button>
          </div>
          <div id="correlationJobStatus" class="job-status">就绪</div>
          <div id="correlationTable" class="table-scroll correlation-table"></div>
          <div class="pager">
            <button id="corrPrevPage" type="button">上一页</button>
            <span id="corrPageInfo">第 1 / 1 页</span>
            <button id="corrNextPage" type="button">下一页</button>
          </div>
        </section>
        <section class="panel">
          <div class="section-head">
            <h2>基金名称匹配</h2>
            <span id="nameMatchSummary" class="inline-status">暂无数据</span>
          </div>
          <div class="tool-grid">
            <label><span>中文名称</span><input id="nameMatchQuery" placeholder="输入基金名称"></label>
            <label><span>历史数据年限</span><select id="nameMatchHistoryYears">
              <option value="0" selected>不限</option>
              <option value="5">≥5年</option>
              <option value="10">≥10年</option>
            </select></label>
            <label><span>购买状态</span><select id="nameMatchPurchaseAvailability">
              <option value="all" selected>全部</option>
              <option value="tradable">可买含限额</option>
              <option value="open">可购买</option>
              <option value="limited">限额</option>
              <option value="closed">不可购买</option>
              <option value="unknown">未知</option>
            </select></label>
            <label><span>截至日期</span><input id="nameMatchAsOf" type="date"></label>
            <button class="primary" id="runNameMatch" type="button">匹配基金</button>
          </div>
          <div id="nameMatchResults" class="table-scroll"></div>
        </section>
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

    const state = {
      result: null,
      chartWindows: {},
      drag: null,
      jobTimers: {},
      correlationRows: [],
      correlationPage: 1,
      correlationSummary: {}
    };
    const $ = (id) => document.getElementById(id);

    function setStatus(message, kind = "") {
      const el = $("status");
      el.className = "status " + kind;
      el.textContent = message;
    }

    function todayText() {
      return new Date().toISOString().slice(0, 10);
    }

    function requestErrorMessage(error) {
      const message = error?.message || "请求失败";
      if (message === "Failed to fetch" || message.includes("NetworkError")) {
        return "无法连接本地网站服务，请确认启动网站窗口仍在运行，然后刷新页面。";
      }
      return message;
    }

    async function postJson(url, payload = {}) {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "请求失败");
      return data;
    }

    async function refreshDataStatus() {
      try {
        const response = await fetch("/api/data-status");
        if (!response.ok) throw new Error("读取数据状态失败");
        renderDataStatus(await response.json());
      } catch (error) {
        $("dataStatus").textContent = error.message;
      }
    }

    function renderDataStatus(data) {
      const catalog = data.fund_catalog || {};
      const coverage = data.coverage || {};
      const correlations = data.correlations || {};
      const purchase = data.purchase_status || {};
      $("dataStatus").textContent = `基金 ${catalog.count || 0} · 覆盖 ${coverage.count || 0} · 申购 ${purchase.count || 0} · 相关 ${correlations.pair_count || 0}`;
    }

    async function startFundCatalogJob() {
      $("refreshCatalog").disabled = true;
      $("dataJobStatus").textContent = "基金列表更新中";
      try {
        const job = await postJson("/api/data/fund-catalog");
        pollJob(job.id, "dataJobStatus", () => {
          $("refreshCatalog").disabled = false;
          refreshDataStatus();
          fetchFundSuggestions(document.querySelector(".fund-code")?.value || "");
        });
      } catch (error) {
        $("refreshCatalog").disabled = false;
        $("dataJobStatus").textContent = error.message;
      }
    }

    async function startCoverageJob() {
      $("buildCoverage").disabled = true;
      $("dataJobStatus").textContent = "覆盖索引生成中";
      try {
        const job = await postJson("/api/data/coverage", {
          as_of: $("coverageAsOf").value || todayText(),
          refresh: $("coverageRefresh").checked
        });
        pollJob(job.id, "dataJobStatus", () => {
          $("buildCoverage").disabled = false;
          refreshDataStatus();
          document.querySelectorAll(".fund-row").forEach((row) => {
            fetchFundDetail(row.querySelector(".fund-code").value, row);
          });
          if ($("nameMatchQuery").value.trim()) matchFundsByName();
        });
      } catch (error) {
        $("buildCoverage").disabled = false;
        $("dataJobStatus").textContent = error.message;
      }
    }

    async function startPurchaseStatusJob() {
      $("refreshPurchaseStatus").disabled = true;
      $("dataJobStatus").textContent = "申购状态更新中";
      try {
        const job = await postJson("/api/data/purchase-status");
        pollJob(job.id, "dataJobStatus", () => {
          $("refreshPurchaseStatus").disabled = false;
          refreshDataStatus();
          fetchFundSuggestions(document.querySelector(".fund-code")?.value || "");
          document.querySelectorAll(".fund-row").forEach((row) => {
            fetchFundDetail(row.querySelector(".fund-code").value, row);
          });
          if ($("nameMatchQuery").value.trim()) matchFundsByName();
        });
      } catch (error) {
        $("refreshPurchaseStatus").disabled = false;
        $("dataJobStatus").textContent = error.message;
      }
    }

    function renderJobStatus(elementId, job) {
      const current = Number(job.current || 0);
      const total = Number(job.total || 0);
      const progress = total > 0 ? ` ${current}/${total}` : "";
      const errors = Number(job.errors || 0) > 0 ? ` · 错误 ${job.errors}` : "";
      const message = job.message || job.status || "";
      $(elementId).textContent = `${message}${progress}${errors}`;
      $(elementId).className = "job-status " + (job.status === "failed" ? "error" : job.status === "completed" ? "ok" : "");
    }

    async function pollJob(jobId, elementId, onDone) {
      clearTimeout(state.jobTimers[jobId]);
      try {
        const response = await fetch(`/api/jobs/${jobId}`);
        const job = await response.json();
        if (!response.ok) throw new Error(job.error || "任务不存在");
        renderJobStatus(elementId, job);
        if (job.status === "completed" || job.status === "failed") {
          delete state.jobTimers[jobId];
          onDone?.(job);
          return;
        }
        state.jobTimers[jobId] = setTimeout(() => pollJob(jobId, elementId, onDone), 900);
      } catch (error) {
        const message = requestErrorMessage(error);
        $(elementId).textContent = message;
        delete state.jobTimers[jobId];
        onDone?.({ status: "failed", error: message });
      }
    }

    async function startCorrelationJob() {
      $("computeCorrelation").disabled = true;
      $("correlationJobStatus").textContent = "相关性计算中";
      try {
        const job = await postJson("/api/correlations", {
          min_history_years: Number($("corrMinHistoryYears").value || 5),
          as_of: $("corrAsOf").value || todayText(),
          query_a: $("corrQueryA").value || "",
          query_b: $("corrQueryB").value || ""
        });
        pollJob(job.id, "correlationJobStatus", (finalJob) => {
          $("computeCorrelation").disabled = false;
          refreshDataStatus();
          if (finalJob.status === "completed") loadCorrelations();
        });
      } catch (error) {
        $("computeCorrelation").disabled = false;
        $("correlationJobStatus").textContent = requestErrorMessage(error);
      }
    }

    const CORR_RANGE_MAP = {
      all: {},
      strong_neg: { min: -1.0001, max: -0.7 },
      mid_neg: { min: -0.7, max: -0.3 },
      weak: { min: -0.3, max: 0.3 },
      mid_pos: { min: 0.3, max: 0.7 },
      strong_pos: { min: 0.7, max: 1.0001 }
    };
    const SHARPE_RANGE_MAP = {
      all: {},
      lt0: { max: 0 },
      "0_1": { min: 0, max: 1 },
      "1_2": { min: 1, max: 2 },
      "2_3": { min: 2, max: 3 },
      gt3: { min: 3 }
    };

    async function loadCorrelations(page = state.correlationPage) {
      state.correlationPage = Math.max(Number(page) || 1, 1);
      const corrRange = CORR_RANGE_MAP[$("corrRange").value] || {};
      const sharpeRange = SHARPE_RANGE_MAP[$("sharpeRange").value] || {};
      const params = new URLSearchParams({
        q_a: $("corrQueryA").value || "",
        q_b: $("corrQueryB").value || "",
        sort: $("corrSort").value,
        page: String(state.correlationPage),
        page_size: $("corrPageSize").value || "10",
        purchase_availability: $("corrPurchaseAvailability").value || "all"
      });
      if (corrRange.min !== undefined) params.set("corr_min", String(corrRange.min));
      if (corrRange.max !== undefined) params.set("corr_max", String(corrRange.max));
      if (sharpeRange.min !== undefined) params.set("sharpe_min", String(sharpeRange.min));
      if (sharpeRange.max !== undefined) params.set("sharpe_max", String(sharpeRange.max));
      try {
        const response = await fetch(`/api/correlations?${params.toString()}`);
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "读取相关性失败");
        state.correlationRows = payload.items || [];
        state.correlationSummary = payload.summary || {};
        state.correlationPage = Number(state.correlationSummary.page || state.correlationPage);
        renderCorrelationSummary(state.correlationSummary);
        renderCorrelationTable(state.correlationRows);
        renderCorrelationPager(state.correlationSummary);
        if (payload.warning) $("correlationJobStatus").textContent = payload.warning;
      } catch (error) {
        $("correlationJobStatus").textContent = requestErrorMessage(error);
      }
    }

    function resetCorrelationPageAndLoad() {
      state.correlationPage = 1;
      loadCorrelations(1);
    }

    function changeCorrelationPage(delta) {
      const summary = state.correlationSummary || {};
      const totalPages = Number(summary.total_pages || 1);
      const nextPage = Math.max(1, Math.min(totalPages, state.correlationPage + delta));
      if (nextPage !== state.correlationPage) loadCorrelations(nextPage);
    }

    function renderCorrelationSummary(summary) {
      const fundCount = Number(summary.fund_count || 0);
      const pairCount = Number(summary.pair_count || 0);
      const filtered = Number(summary.filtered_count || 0);
      const page = Number(summary.page || 1);
      const totalPages = Number(summary.total_pages || 1);
      const generated = summary.generated_at ? ` · ${summary.generated_at}` : "";
      $("correlationSummary").textContent = `基金 ${fundCount} · 组合 ${pairCount} · 当前 ${filtered} · 第 ${page}/${totalPages} 页${generated}`;
    }

    function renderCorrelationPager(summary) {
      const page = Number(summary.page || 1);
      const totalPages = Number(summary.total_pages || 1);
      const filtered = Number(summary.filtered_count || 0);
      $("corrPageInfo").textContent = `第 ${page} / ${totalPages} 页 · 共 ${filtered} 条`;
      $("corrPrevPage").disabled = page <= 1;
      $("corrNextPage").disabled = page >= totalPages;
    }

    const CORR_SORT_CYCLE = {
      correlation: ["corr_desc", "corr_asc"],
      sharpe_b: ["sharpe_b_desc", "sharpe_b_asc"]
    };
    const CORR_SORT_LABEL = {
      corr_desc: "正相关 ↓",
      corr_asc: "负相关 ↑",
      sharpe_b_desc: "Sharpe 高 ↓",
      sharpe_b_asc: "Sharpe 低 ↑"
    };

    function sortIconMarkup(column, currentSort) {
      const cycle = CORR_SORT_CYCLE[column];
      const isActive = cycle && cycle.indexOf(currentSort) >= 0;
      const cls = isActive ? "sort-icon is-active" : "sort-icon";
      const symbol = !isActive ? "↕" : (currentSort.endsWith("_desc") ? "↓" : "↑");
      const fallback = column === "correlation" ? "按相关系数排序" : "按 B Sharpe 排序";
      const label = (isActive ? CORR_SORT_LABEL[currentSort] : "") || fallback;
      return `<button type="button" class="${cls}" data-column="${column}" title="${label}">${symbol}</button>`;
    }

    function applyCorrelationSort(column) {
      const cycle = CORR_SORT_CYCLE[column];
      if (!cycle) return;
      const current = $("corrSort").value;
      const idx = cycle.indexOf(current);
      const next = idx >= 0 ? (idx + 1) % cycle.length : 0;
      $("corrSort").value = cycle[next];
      resetCorrelationPageAndLoad();
    }

    function fundCellMarkup(code, name, fundType, availability, purchaseStatus, purchaseLimitText) {
      const status = purchaseStatus ? ` · ${escapeHtml(purchaseStatus)}` : "";
      const limit = purchaseLimitText ? ` · ${escapeHtml(purchaseLimitText)}` : "";
      return `
        <div class="fund-cell">
          <span class="fund-code-text">${escapeHtml(code || "")}</span>
          <span class="fund-name-text">${escapeHtml(name || "未命名基金")}</span>
          <span class="fund-type-text">类型：${escapeHtml(fundType || "暂无")}</span>
          <span class="fund-type-text">${purchaseBadgeMarkup(availability)}${status}${limit}</span>
        </div>
      `;
    }

    function renderCorrelationTable(rows) {
      if (!rows.length) {
        $("correlationTable").innerHTML = `<div class="empty">暂无相关性数据</div>`;
        return;
      }
      const currentSort = $("corrSort").value;
      $("correlationTable").innerHTML = `
        <table>
          <thead>
            <tr>
              <th>基金A</th>
              <th>基金B</th>
              <th>相关系数 ${sortIconMarkup("correlation", currentSort)}</th>
              <th>A Sharpe</th>
              <th>B Sharpe ${sortIconMarkup("sharpe_b", currentSort)}</th>
              <th>样本数</th>
            </tr>
          </thead>
          <tbody>
            ${rows.map((row) => `
              <tr>
                <td>${fundCellMarkup(row.code_a, row.name_a, row.fund_type_a, row.availability_a, row.purchase_status_a, row.purchase_limit_text_a)}</td>
                <td>${fundCellMarkup(row.code_b, row.name_b, row.fund_type_b, row.availability_b, row.purchase_status_b, row.purchase_limit_text_b)}</td>
                <td>${formatCorrelation(row.correlation)}</td>
                <td>${formatSharpe(row.sharpe_a)}</td>
                <td>${formatSharpe(row.sharpe_b)}</td>
                <td>${Number(row.observations || 0).toFixed(0)}</td>
              </tr>`).join("")}
          </tbody>
        </table>
      `;
      $("correlationTable").querySelectorAll(".sort-icon").forEach((btn) => {
        btn.addEventListener("click", () => applyCorrelationSort(btn.dataset.column));
      });
    }

    function formatCorrelation(value) {
      const number = Number(value);
      return Number.isFinite(number) ? number.toFixed(4) : "暂无";
    }
    function formatSharpe(value) {
      const number = Number(value);
      return Number.isFinite(number) ? number.toFixed(3) : "暂无";
    }
    function formatYears(value) {
      const number = Number(value);
      return Number.isFinite(number) ? number.toFixed(2) : "暂无";
    }
    function purchaseBadgeMarkup(availability) {
      const text = availability || "未知";
      const cls = text === "可购买" ? "purchase-open" : text === "限额" ? "purchase-limited" : text === "不可购买" ? "purchase-closed" : "purchase-unknown";
      return `<span class="purchase-badge ${cls}">${escapeHtml(text)}</span>`;
    }

    async function matchFundsByName() {
      const query = $("nameMatchQuery").value.trim();
      if (!query) {
        $("nameMatchSummary").textContent = "暂无数据";
        renderNameMatchResults([]);
        return;
      }
      const params = new URLSearchParams({ q: query, name_only: "1", limit: "100" });
      params.set("purchase_availability", $("nameMatchPurchaseAvailability").value || "all");
      if ($("nameMatchHistoryYears").value !== "0") {
        params.set("min_history_years", $("nameMatchHistoryYears").value);
        params.set("as_of", $("nameMatchAsOf").value || todayText());
      }
      try {
        const response = await fetch(`/api/funds?${params.toString()}`);
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "匹配失败");
        const items = payload.items || [];
        renderNameMatchResults(items);
        $("nameMatchSummary").textContent = `匹配 ${items.length} 只`;
        if (payload.warning) $("nameMatchSummary").textContent = payload.warning;
      } catch (error) {
        $("nameMatchSummary").textContent = error.message;
      }
    }

    function renderNameMatchResults(rows) {
      if (!rows.length) {
        $("nameMatchResults").innerHTML = `<div class="empty">暂无匹配基金</div>`;
        return;
      }
      $("nameMatchResults").innerHTML = `
        <table>
          <thead>
            <tr>
              <th>代码</th>
              <th>名称</th>
              <th>类型</th>
              <th>购买状态</th>
              <th>申购状态</th>
              <th>限额</th>
              <th>开始日期</th>
              <th>最新日期</th>
              <th>历史年限</th>
            </tr>
          </thead>
          <tbody>
            ${rows.map((row) => `
              <tr>
                <td>${escapeHtml(row.code || "")}</td>
                <td>${escapeHtml(row.name || "")}</td>
                <td>${escapeHtml(row.fund_type || "暂无")}</td>
                <td>${purchaseBadgeMarkup(row.availability)}</td>
                <td>${escapeHtml(row.purchase_status || "暂无")}</td>
                <td>${escapeHtml(row.purchase_limit_text || "暂无")}</td>
                <td>${escapeHtml(row.data_start || "暂无")}</td>
                <td>${escapeHtml(row.data_end || "暂无")}</td>
                <td>${formatYears(row.history_years)}</td>
              </tr>`).join("")}
          </tbody>
        </table>
      `;
    }

    function addFundRow(code = "", weight = "") {
      const row = document.createElement("div");
      row.className = "fund-row";
      row.innerHTML = `
        <input class="fund-code" list="fundSuggestions" inputmode="numeric" maxlength="6" value="${code}">
        <input class="fund-weight" type="number" min="0" step="0.01" value="${weight}">
        <button class="icon remove-fund" type="button" title="删除基金">×</button>
        <div class="fund-meta">名称：加载中 · 开始：加载中</div>
      `;
      row.querySelector(".remove-fund").addEventListener("click", () => {
        row.remove();
        if (!document.querySelector(".fund-row")) addFundRow();
      });
      const codeInput = row.querySelector(".fund-code");
      codeInput.addEventListener("input", debounce(() => {
        fetchFundSuggestions(codeInput.value);
        fetchFundDetail(codeInput.value, row);
      }, 220));
      $("fundRows").appendChild(row);
      fetchFundDetail(code, row);
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
      const params = new URLSearchParams({ q: query });
      if ($("minHistoryYears").value !== "0") {
        params.set("min_history_years", $("minHistoryYears").value);
        params.set("as_of", $("endDate").value || new Date().toISOString().slice(0, 10));
      }
      const response = await fetch(`/api/funds?${params.toString()}`);
      if (!response.ok) return;
      const payload = await response.json();
      if (payload.warning) setStatus(payload.warning, "error");
      const list = $("fundSuggestions");
      list.innerHTML = "";
      payload.items.forEach((item) => {
        const option = document.createElement("option");
        option.value = item.code;
        const purchase = item.availability ? ` ${item.availability}` : "";
        const limit = item.purchase_limit_text ? ` 限额:${item.purchase_limit_text}` : "";
        option.label = `${item.code} ${item.name} ${item.fund_type}${purchase}${limit} ${item.data_start ? "开始:" + item.data_start : ""}`;
        list.appendChild(option);
      });
    }

    async function fetchFundDetail(code, row) {
      const raw = String(code || "").trim();
      const meta = row.querySelector(".fund-meta");
      if (!raw) {
        meta.textContent = "名称：暂无 · 开始：暂无";
        return;
      }
      const normalized = raw.padStart(6, "0");
      if (normalized.length !== 6 || !/^\d{6}$/.test(normalized)) {
        meta.textContent = "名称：暂无 · 开始：暂无";
        return;
      }
      try {
        const params = new URLSearchParams({ q: normalized });
        const response = await fetch(`/api/funds?${params.toString()}`);
        if (!response.ok) throw new Error("查询失败");
        const payload = await response.json();
        const item = (payload.items || []).find((entry) => entry.code === normalized) || payload.items?.[0];
        if (!item) {
          meta.textContent = "名称：未找到 · 开始：暂无";
          return;
        }
        const name = item.name || "未命名基金";
        const start = item.data_start || "暂无";
        const type = item.fund_type ? ` · ${item.fund_type}` : "";
        const availability = item.availability || "未知";
        const purchaseStatus = item.purchase_status ? ` · ${item.purchase_status}` : "";
        const limit = item.purchase_limit_text ? ` · 限额：${item.purchase_limit_text}` : "";
        meta.textContent = `${name}${type} · 开始：${start} · ${availability}${purchaseStatus}${limit}`;
        meta.title = `${item.code} ${name} ${item.fund_type || ""} 开始：${start} ${availability} ${item.purchase_status || ""} ${item.purchase_limit_text || ""}`;
      } catch (error) {
        meta.textContent = "名称：查询失败 · 开始：暂无";
      }
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
        rebalance_frequency: $("rebalanceFrequency").value,
        fee_rate: Number($("feeRate").value || 0),
        min_history_years: Number($("minHistoryYears").value || 0),
        contribution_amount: Number($("contributionAmount").value || 0),
        contribution_frequency: $("contributionFrequency").value,
        contribution_weekday: $("contributionWeekday").value,
        refresh: $("refresh").checked
      };
    }

    function updateContributionWeekdayState() {
      const weekly = $("contributionFrequency").value === "weekly";
      $("contributionWeekdayLabel").hidden = !weekly;
      $("contributionWeekday").disabled = !weekly;
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
      renderAnnualMetrics(data.annual_metrics || []);
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
        ["total_contributions", "累计投入", formatMoney],
        ["net_profit", "累计盈利", formatMoney],
        ["return_on_contributions", "投入收益率", formatPercent],
        ["volatility", "波动率", formatPercent],
        ["sharpe", "Sharpe", (v) => Number(v).toFixed(3)],
        ["total_fees", "累计费用", formatMoney],
        ["rebalance_count", "再平衡次数", (v) => Number(v).toFixed(0)],
        ["average_turnover", "平均换手", formatPercent]
      ];
      $("metrics").innerHTML = specs.map(([key, name, formatter]) => `
        <div class="metric">
          <div class="name">${name}</div>
          <div class="value">${formatter(metrics[key] ?? 0)}</div>
        </div>
      `).join("");
    }

    function renderAnnualMetrics(rows) {
      if (!rows.length) {
        $("annualMetrics").innerHTML = `<div class="empty">暂无年度指标</div>`;
        return;
      }
      $("annualMetrics").innerHTML = `
        <table>
          <thead>
            <tr>
              <th>年份</th>
              <th>期末资产</th>
              <th>年度收益</th>
              <th>最大回撤</th>
              <th>年度投入</th>
              <th>年度盈利</th>
              <th>投入收益率</th>
              <th>费用</th>
              <th>再平衡</th>
            </tr>
          </thead>
          <tbody>
            ${rows.map((row) => `
              <tr>
                <td>${Number(row.year).toFixed(0)}</td>
                <td>${formatMoney(row.end_value)}</td>
                <td>${formatPercent(row.total_return)}</td>
                <td>${formatPercent(row.max_drawdown)}</td>
                <td>${formatMoney(row.total_contributions)}</td>
                <td>${formatMoney(row.net_profit)}</td>
                <td>${formatPercent(row.return_on_contributions)}</td>
                <td>${formatMoney(row.total_fees)}</td>
                <td>${Number(row.rebalance_count).toFixed(0)}</td>
              </tr>`).join("")}
          </tbody>
        </table>
      `;
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
      const fullRows = rows;
      const windowRange = normalizeChartWindow(canvasId, fullRows.length);
      rows = fullRows.slice(windowRange.start, windowRange.end + 1);
      if (!rows.length) return;
      const values = rows.map((row) => row[1]).filter((value) => Number.isFinite(value));
      if (!values.length) return;
      let min = Math.min(...values);
      let max = Math.max(...values);
      if (min === max) { min -= 1; max += 1; }

      const pad = { left: 58, right: 16, top: 16, bottom: 34 };
      const cw = width - pad.left - pad.right;
      const ch = height - pad.top - pad.bottom;
      canvas.dataset.padLeft = String(pad.left);
      canvas.dataset.padRight = String(pad.right);
      canvas.dataset.visibleStart = String(windowRange.start);
      canvas.dataset.visibleEnd = String(windowRange.end);
      canvas.dataset.rowCount = String(fullRows.length);
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
      drawXAxisTicks(ctx, rows, pad, width, height);

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
      if (state.drag && state.drag.canvasId === canvasId) {
        const x1 = Math.min(state.drag.startX, state.drag.currentX);
        const x2 = Math.max(state.drag.startX, state.drag.currentX);
        if (x2 - x1 > 3) {
          ctx.fillStyle = "rgba(36, 125, 143, 0.12)";
          ctx.fillRect(x1, pad.top, x2 - x1, ch);
          ctx.strokeStyle = "rgba(36, 125, 143, 0.75)";
          ctx.strokeRect(x1, pad.top, x2 - x1, ch);
        }
      }
      $(scaleId).textContent = `${formatAxis(min, suffix)} / ${formatAxis(max, suffix)}`;
      if (windowRange.start > 0 || windowRange.end < fullRows.length - 1) {
        $(scaleId).textContent += ` · ${fullRows[windowRange.start][0]} 至 ${fullRows[windowRange.end][0]}`;
      }
    }

    function drawXAxisTicks(ctx, rows, pad, width, height) {
      const chartWidth = width - pad.left - pad.right;
      const chartHeight = height - pad.top - pad.bottom;
      const axisY = pad.top + chartHeight;
      const maxTicks = width >= 760 ? 6 : width >= 520 ? 5 : 3;
      const indexes = buildTickIndexes(rows.length, maxTicks);
      ctx.font = "12px Arial";
      ctx.textBaseline = "top";

      indexes.forEach((index) => {
        const x = pad.left + (index / Math.max(rows.length - 1, 1)) * chartWidth;
        ctx.strokeStyle = "#edf1f5";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, pad.top);
        ctx.lineTo(x, axisY);
        ctx.stroke();

        ctx.strokeStyle = "#cfd7e2";
        ctx.beginPath();
        ctx.moveTo(x, axisY);
        ctx.lineTo(x, axisY + 5);
        ctx.stroke();

        ctx.fillStyle = "#66717f";
        ctx.textAlign = index === 0 ? "left" : index === rows.length - 1 ? "right" : "center";
        ctx.fillText(formatDateTick(rows[index][0], rows[0][0], rows[rows.length - 1][0]), x, axisY + 9);
      });
      ctx.textAlign = "left";
      ctx.textBaseline = "alphabetic";
    }

    function buildTickIndexes(length, maxTicks) {
      if (length <= 1) return [0];
      const count = Math.min(maxTicks, length);
      const indexes = [];
      for (let i = 0; i < count; i += 1) {
        indexes.push(Math.round((i / Math.max(count - 1, 1)) * (length - 1)));
      }
      return [...new Set(indexes)];
    }

    function formatDateTick(value, first, last) {
      const firstDate = new Date(`${first}T00:00:00`);
      const lastDate = new Date(`${last}T00:00:00`);
      const elapsedDays = (lastDate - firstDate) / 86400000;
      if (!Number.isFinite(elapsedDays)) return value;
      if (elapsedDays > 370) return value.slice(0, 7);
      return value.slice(5);
    }

    function normalizeChartWindow(canvasId, rowCount) {
      const current = state.chartWindows[canvasId];
      if (!current || rowCount <= 0) return { start: 0, end: Math.max(rowCount - 1, 0) };
      const start = Math.max(0, Math.min(current.start, rowCount - 1));
      const end = Math.max(start, Math.min(current.end, rowCount - 1));
      return { start, end };
    }

    function resetChart(canvasId) {
      delete state.chartWindows[canvasId];
      if (state.result) renderAll(state.result);
    }

    function setupChartZoom(canvasId) {
      const canvas = $(canvasId);
      canvas.addEventListener("pointerdown", (event) => {
        if (!state.result) return;
        const rect = canvas.getBoundingClientRect();
        const x = event.clientX - rect.left;
        state.drag = { canvasId, startX: x, currentX: x };
        canvas.setPointerCapture(event.pointerId);
      });
      canvas.addEventListener("pointermove", (event) => {
        if (!state.drag || state.drag.canvasId !== canvasId) return;
        const rect = canvas.getBoundingClientRect();
        state.drag.currentX = Math.max(0, Math.min(event.clientX - rect.left, rect.width));
        if (state.result) renderAll(state.result);
      });
      canvas.addEventListener("pointerup", (event) => {
        if (!state.drag || state.drag.canvasId !== canvasId) return;
        const drag = state.drag;
        state.drag = null;
        canvas.releasePointerCapture(event.pointerId);
        const rect = canvas.getBoundingClientRect();
        const width = rect.width;
        const left = Number(canvas.dataset.padLeft || 58);
        const right = width - Number(canvas.dataset.padRight || 16);
        const x1 = Math.max(left, Math.min(drag.startX, drag.currentX));
        const x2 = Math.min(right, Math.max(drag.startX, drag.currentX));
        if (x2 - x1 < 12) {
          if (state.result) renderAll(state.result);
          return;
        }
        const visibleStart = Number(canvas.dataset.visibleStart || 0);
        const visibleEnd = Number(canvas.dataset.visibleEnd || 0);
        const visibleCount = Math.max(visibleEnd - visibleStart, 1);
        const startRatio = (x1 - left) / Math.max(right - left, 1);
        const endRatio = (x2 - left) / Math.max(right - left, 1);
        const nextStart = visibleStart + Math.floor(startRatio * visibleCount);
        const nextEnd = visibleStart + Math.ceil(endRatio * visibleCount);
        if (nextEnd > nextStart) {
          state.chartWindows[canvasId] = { start: nextStart, end: nextEnd };
        }
        if (state.result) renderAll(state.result);
      });
      canvas.addEventListener("pointercancel", () => {
        state.drag = null;
        if (state.result) renderAll(state.result);
      });
      canvas.addEventListener("dblclick", () => resetChart(canvasId));
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
    $("refreshCatalog").addEventListener("click", startFundCatalogJob);
    $("buildCoverage").addEventListener("click", startCoverageJob);
    $("refreshPurchaseStatus").addEventListener("click", startPurchaseStatusJob);
    $("computeCorrelation").addEventListener("click", startCorrelationJob);
    $("refreshCorrelation").addEventListener("click", () => loadCorrelations());
    $("corrQueryA").addEventListener("input", debounce(resetCorrelationPageAndLoad, 250));
    $("corrQueryB").addEventListener("input", debounce(resetCorrelationPageAndLoad, 250));
    $("corrSort").addEventListener("change", resetCorrelationPageAndLoad);
    $("corrPageSize").addEventListener("change", resetCorrelationPageAndLoad);
    $("corrRange").addEventListener("change", resetCorrelationPageAndLoad);
    $("sharpeRange").addEventListener("change", resetCorrelationPageAndLoad);
    $("corrPurchaseAvailability").addEventListener("change", resetCorrelationPageAndLoad);
    $("corrPrevPage").addEventListener("click", () => changeCorrelationPage(-1));
    $("corrNextPage").addEventListener("click", () => changeCorrelationPage(1));
    $("runNameMatch").addEventListener("click", matchFundsByName);
    $("nameMatchQuery").addEventListener("input", debounce(matchFundsByName, 300));
    $("nameMatchHistoryYears").addEventListener("change", matchFundsByName);
    $("nameMatchPurchaseAvailability").addEventListener("change", matchFundsByName);
    $("nameMatchAsOf").addEventListener("change", matchFundsByName);
    $("resetValueChart").addEventListener("click", () => resetChart("valueChart"));
    $("resetDrawdownChart").addEventListener("click", () => resetChart("drawdownChart"));
    $("contributionFrequency").addEventListener("change", updateContributionWeekdayState);
    window.addEventListener("resize", () => {
      if (state.result) renderAll(state.result);
    });
    $("coverageAsOf").value = todayText();
    $("corrAsOf").value = todayText();
    $("nameMatchAsOf").value = todayText();
    setupChartZoom("valueChart");
    setupChartZoom("drawdownChart");
    defaultFunds.forEach(([code, weight]) => addFundRow(code, weight));
    renderMetrics({});
    renderAnnualMetrics([]);
    $("holdings").innerHTML = `<div class="empty">暂无持仓</div>`;
    renderNameMatchResults([]);
    updateContributionWeekdayState();
    refreshDataStatus();
    loadCorrelations();
  </script>
</body>
</html>
"""


_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()


def start_job(kind: str, target) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    now = _timestamp_text()
    job = {
        "id": job_id,
        "kind": kind,
        "status": "queued",
        "message": "排队中",
        "current": 0,
        "total": 0,
        "errors": 0,
        "created_at": now,
        "started_at": "",
        "completed_at": "",
        "result": {},
        "error": "",
    }
    with _JOBS_LOCK:
        _JOBS[job_id] = job

    def progress(update: dict[str, Any]) -> None:
        update_job(job_id, **update)

    def runner() -> None:
        update_job(job_id, status="running", started_at=_timestamp_text(), message="运行中")
        try:
            result = target(progress)
            update_job(
                job_id,
                status="completed",
                completed_at=_timestamp_text(),
                message="完成",
                result=result,
            )
        except Exception as exc:  # noqa: BLE001
            update_job(
                job_id,
                status="failed",
                completed_at=_timestamp_text(),
                message=str(exc),
                error=str(exc),
            )

    threading.Thread(target=runner, name=f"fund-backtest-{kind}", daemon=True).start()
    return get_job(job_id) or job


def update_job(job_id: str, **updates: Any) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job.update(updates)


def get_job(job_id: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job is not None else None


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
            min_history_years = _float_or_default(params.get("min_history_years", [0])[0], 0.0)
            as_of = _blank_to_none(params.get("as_of", [""])[0])
            limit = int(_float_or_default(params.get("limit", [20])[0], 20))
            name_only = str(params.get("name_only", [""])[0]).strip().lower() in {"1", "true", "yes"}
            purchase_availability = params.get("purchase_availability", [""])[0]
            payload = search_funds_payload(
                query,
                limit=limit,
                min_history_years=min_history_years,
                as_of=as_of,
                name_only=name_only,
                purchase_availability=purchase_availability,
            )
            self._send_json(payload)
            return
        if parsed.path == "/api/data-status":
            self._send_json(get_data_status())
            return
        if parsed.path == "/api/correlations":
            try:
                params = parse_qs(parsed.query)

                def _optional_float(name: str) -> float | None:
                    values = params.get(name)
                    if not values or values[0] == "":
                        return None
                    try:
                        value = float(values[0])
                    except (TypeError, ValueError):
                        return None
                    return value if math.isfinite(value) else None

                payload = load_correlation_payload(
                    query=params.get("q", [""])[0],
                    query_a=params.get("q_a", [""])[0],
                    query_b=params.get("q_b", [""])[0],
                    sort=params.get("sort", ["abs_desc"])[0],
                    limit=int(_float_or_default(params.get("limit", [200])[0], 200)),
                    page=int(_float_or_default(params.get("page", [1])[0], 1)),
                    page_size=int(_float_or_default(params.get("page_size", [10])[0], 10)),
                    corr_min=_optional_float("corr_min"),
                    corr_max=_optional_float("corr_max"),
                    sharpe_min=_optional_float("sharpe_min"),
                    sharpe_max=_optional_float("sharpe_max"),
                    purchase_availability=params.get("purchase_availability", [""])[0],
                )
                self._send_json(payload)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if parsed.path.startswith("/api/jobs/"):
            job_id = parsed.path.rsplit("/", 1)[-1]
            job = get_job(job_id)
            if job is None:
                self._send_json({"error": "任务不存在"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(job)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/backtest":
                payload = self._read_json()
                result = run_backtest_payload(payload)
                self._send_json(result)
                return
            if parsed.path == "/api/data/fund-catalog":
                job = start_job("fund_catalog", lambda progress: refresh_fund_catalog(progress_callback=progress))
                self._send_json(job, status=HTTPStatus.ACCEPTED)
                return
            if parsed.path == "/api/data/coverage":
                payload = self._read_json()
                job = start_job(
                    "coverage",
                    lambda progress: build_coverage_index(
                        as_of=_blank_to_none(payload.get("as_of")),
                        refresh=bool(payload.get("refresh", False)),
                        progress_callback=progress,
                    ),
                )
                self._send_json(job, status=HTTPStatus.ACCEPTED)
                return
            if parsed.path == "/api/data/purchase-status":
                job = start_job("purchase_status", lambda progress: refresh_purchase_status(progress_callback=progress))
                self._send_json(job, status=HTTPStatus.ACCEPTED)
                return
            if parsed.path == "/api/correlations":
                payload = self._read_json()
                job = start_job(
                    "correlations",
                    lambda progress: compute_correlation_index(
                        min_history_years=_float_or_default(payload.get("min_history_years"), 5.0),
                        as_of=_blank_to_none(payload.get("as_of")),
                        query=str(payload.get("query") or ""),
                        query_a=str(payload.get("query_a") or ""),
                        query_b=str(payload.get("query_b") or ""),
                        progress_callback=progress,
                    ),
                )
                self._send_json(job, status=HTTPStatus.ACCEPTED)
                return
            self.send_error(HTTPStatus.NOT_FOUND)
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
            json.dumps(_json_safe(payload), ensure_ascii=False, allow_nan=False).encode("utf-8"),
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
    initial_cash = _float_or_default(payload.get("initial_cash"), 10000.0)
    min_history_years = _float_or_default(payload.get("min_history_years"), 0.0)
    end = _blank_to_none(payload.get("end"))

    validate_fund_history_requirement(
        weights,
        min_history_years=min_history_years,
        as_of=end,
        coverage_path=DEFAULT_COVERAGE_PATH,
        max_stale_days=DEFAULT_MAX_STALE_DAYS,
    )

    result = run_backtest(
        weights,
        initial_cash=initial_cash,
        start=_blank_to_none(payload.get("start")),
        end=end,
        cache_dir=str(payload.get("cache_dir") or "data/fund_cache"),
        rebalance_frequency=str(payload.get("rebalance_frequency") or "none"),  # type: ignore[arg-type]
        fee_rate=float(payload.get("fee_rate") or 0.0),
        contribution_amount=float(payload.get("contribution_amount") or 0.0),
        contribution_frequency=str(payload.get("contribution_frequency") or "monthly"),  # type: ignore[arg-type]
        contribution_weekday=str(payload.get("contribution_weekday") or "monday"),  # type: ignore[arg-type]
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
        "annual_metrics": result.annual_metrics,
        "settings": result.metadata,
        "weights": normalized,
        "final_holdings": holdings,
        "series": [
            {
                "date": index.strftime("%Y-%m-%d"),
                "total": float(row["total"]),
                "drawdown": float(row["drawdown"]),
                "cumulative_contributions": float(row.get("cumulative_contributions", 0.0)),
            }
            for index, row in sampled.iterrows()
        ],
    }


def search_funds(
    query: str,
    *,
    limit: int = 20,
    min_history_years: float = 0.0,
    as_of: str | None = None,
    name_only: bool = False,
    purchase_availability: str = "",
) -> list[dict[str, str]]:
    return search_funds_payload(
        query,
        limit=limit,
        min_history_years=min_history_years,
        as_of=as_of,
        name_only=name_only,
        purchase_availability=purchase_availability,
    )["items"]


def search_funds_payload(
    query: str,
    *,
    limit: int = 20,
    min_history_years: float = 0.0,
    as_of: str | None = None,
    name_only: bool = False,
    purchase_availability: str = "",
) -> dict[str, Any]:
    catalog = load_fund_catalog()
    if catalog.empty:
        return {"items": []}
    limit = max(min(int(limit), 200), 1)
    q = str(query).strip().lower()
    if q:
        name_mask = catalog["name"].str.lower().str.contains(q, na=False, regex=False)
        if name_only:
            mask = name_mask
        else:
            mask = (
                catalog["code"].str.lower().str.contains(q, na=False, regex=False)
                | name_mask
                | catalog["fund_type"].str.lower().str.contains(q, na=False, regex=False)
                | catalog["pinyin"].str.lower().str.contains(q, na=False, regex=False)
            )
        catalog = catalog.loc[mask]
    warning = ""
    catalog = _attach_coverage_fields(catalog)
    catalog = attach_purchase_status_fields(catalog, status_path=DEFAULT_PURCHASE_STATUS_PATH)
    catalog = filter_purchase_availability(catalog, purchase_availability)
    if min_history_years > 0:
        coverage_path = Path(DEFAULT_COVERAGE_PATH)
        if coverage_path.exists():
            coverage = filter_coverage(
                load_coverage_index(coverage_path),
                min_history_years=min_history_years,
                as_of=as_of,
                max_stale_days=DEFAULT_MAX_STALE_DAYS,
            )
            catalog = catalog.loc[catalog["code"].isin(set(coverage["code"]))]
        else:
            warning = "历史覆盖索引不存在，请在数据管理里生成，当前显示未筛选结果"
    if not Path(DEFAULT_PURCHASE_STATUS_PATH).exists():
        warning = _join_warning(warning, "申购状态索引不存在，请在数据管理里点击更新申购状态")
    payload: dict[str, Any] = {"items": catalog.head(limit).to_dict(orient="records")}
    if warning:
        payload["warning"] = warning
    return payload


def load_fund_catalog() -> pd.DataFrame:
    return load_screening_fund_catalog()


def _attach_coverage_fields(catalog: pd.DataFrame) -> pd.DataFrame:
    output = catalog.copy()
    for column in ["data_start", "data_end", "history_years"]:
        if column not in output.columns:
            output[column] = ""
    coverage_path = Path(DEFAULT_COVERAGE_PATH)
    if not coverage_path.exists() or output.empty:
        return output
    coverage = load_coverage_index(coverage_path)[["code", "data_start", "data_end", "history_years"]]
    output = output.drop(columns=["data_start", "data_end", "history_years"], errors="ignore")
    return output.merge(coverage, on="code", how="left").fillna("")


def _join_warning(left: str, right: str) -> str:
    if left and right:
        return f"{left}。{right}"
    return left or right


def run_server(host: str = "127.0.0.1", port: int = 8000, *, open_browser: bool = False) -> None:
    server = _create_server(host, port)
    actual_port = int(server.server_address[1])
    url = f"http://{host}:{actual_port}/"
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    print(f"Fund backtest UI running at {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down")
    finally:
        server.server_close()


def _create_server(host: str, port: int, *, attempts: int = 20) -> ThreadingHTTPServer:
    for candidate in range(port, port + attempts):
        try:
            return ThreadingHTTPServer((host, candidate), BacktestRequestHandler)
        except OSError as exc:
            if _is_port_in_use(exc):
                continue
            raise
    raise OSError(f"No available port found from {port} to {port + attempts - 1}.")


def _is_port_in_use(exc: OSError) -> bool:
    return getattr(exc, "winerror", None) == 10048 or getattr(exc, "errno", None) in {48, 98, 10048}


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


def _timestamp_text() -> str:
    return pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")


def _float_or_default(value: Any, default: float) -> float:
    if value is None:
        return default
    text = str(value).strip()
    return default if text == "" else float(text)


def _downsample_frame(frame: pd.DataFrame, *, max_points: int) -> pd.DataFrame:
    if len(frame) <= max_points:
        return frame
    step = max(len(frame) // max_points, 1)
    sampled = frame.iloc[::step]
    if sampled.index[-1] != frame.index[-1]:
        sampled = pd.concat([sampled, frame.iloc[[-1]]])
    return sampled


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


if __name__ == "__main__":
    raise SystemExit(main())
