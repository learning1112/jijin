# 基金回测系统 (jijin)

基于天天基金（东方财富）公开数据的基金组合回测、筛选与相关性分析工具，自带本地网页界面，无需数据库，开箱即用。

## 功能特性

- **组合回测**：输入基金代码与权重，设置起止日期、再平衡频率（月度/季度/年度/不限）、交易费率，得到盈亏曲线（PnL，资产减累计投入）、回撤曲线与汇总指标（总收益、年化收益、最大回撤、波动率、夏普比率等）。
- **定投策略（DCA）**：支持按周（可指定星期几）、按月定投，配合初始资金与定投金额模拟长期定投效果，并展示投入、盈利、费用等明细。
- **年度指标**：按自然年展示收益、回撤、投入、盈利和费用。
- **数据管理**：一键更新基金列表目录、生成历史覆盖索引、刷新申购状态；本地缓存净值数据，重复回测无需重新抓取。
- **历史年限筛选**：按实际净值数据覆盖长度（非成立日期）筛选基金，支持不限、5 年以上、10 年以上。
- **相关性分析**：对 5 年以上基金按日期对齐净值、前值填充缺失，基于日变化量计算两两 Pearson 相关，热力图 + 表格展示。
- **组合方案管理**：在网页中保存/加载/删除回测方案，方便复用常用组合。
- **图表交互**：盈亏曲线与回撤图支持拖拽缩放查看局部细节。

## 快速开始

### 安装依赖

方式一：pip

```bash
pip install -r requirements.txt
```

方式二：conda

```bash
conda env create -f environment.yml
conda activate jijin-backtest
```

需要 Python 3.10+。

### 启动网页

Windows 用户双击项目根目录的 `启动网站.bat`（停止网站用 `停止网站.bat`），或手动执行：

```bash
python -m fund_backtest.webapp --open
```

默认地址 `http://127.0.0.1:8000/`，端口被占用时会自动顺延；`--host`/`--port` 可自定义监听地址。

### 命令行回测

`fund_backtest` 也可以作为 Python 库使用：

```python
from fund_backtest import EastmoneyFundClient, run_backtest

client = EastmoneyFundClient()
result = run_backtest(
    {"000307": 0.25, "511010": 0.25, "012693": 0.25, "513110": 0.25},
    start="2021-01-01",
    initial_cash=10000,
    rebalance_frequency="monthly",
    fee_rate=0.001,
    client=client,
)
print(result.metrics)
```

`examples/` 目录下提供了 Lump-sum（一次性投入）与 DCA（定投）两种参数示例。

## 目录结构

```
jijin/
├── fund_backtest/          # 核心包
│   ├── backtest.py         #   回测引擎（再平衡、定投、指标计算）
│   ├── cache.py            #   净值 CSV 本地缓存
│   ├── correlation.py      #   两两相关性分析与索引
│   ├── data_management.py  #   基金目录/覆盖索引/申购状态更新
│   ├── eastmoney.py        #   天天基金数据抓取客户端
│   ├── purchase_status.py  #   申购状态字段与过滤
│   ├── report.py           #   HTML 回测报告生成
│   ├── screening.py        #   历史年限筛选
│   └── webapp.py           #   本地网页应用（入口）
├── scripts/                # 研究脚本
│   ├── sweep_weights.py    #   组合权重网格遍历，指标汇总到 CSV
│   ├── replace_bond_sweep.py # 固定权重下候选债基替换回测
│   └── stop_webapp.ps1     #   停止本地网页进程
├── tests/                  # 单元测试（pytest / unittest）
├── examples/               # 回测参数示例
├── data/                   # 本地运行数据（不上传）
└── output/                 # 回测输出（不上传）
```

## 数据口径

- 非货币基金优先使用天天基金的**累计净值**走势，缺失时回退到单位净值。
- 相关性计算先按日期对齐净值，缺失值用最近的前值填充，再用第 t 天净值相对前一日的变化量计算 Pearson 相关。
- 历史年限按实际净值数据覆盖长度判断，不按基金成立日期判断。
- 申购状态以天天基金页面披露为准，仅供筛选参考。

## 本地数据说明

`data/` 与 `output/` 为本地运行数据，已通过 `.gitignore` 排除：

- `data/fund_cache/`：基金历史净值缓存
- `data/fund_codes.csv`：基金列表目录（网页“数据管理”更新）
- `data/fund_coverage.csv`：历史覆盖索引
- `data/fund_correlations.csv`：两两相关性结果
- `data/portfolios/`：网页保存的回测方案

首次使用建议先在网页“数据管理”中更新基金列表并生成覆盖索引。

## 运行测试

```bash
python -m pytest tests/
```

## 免责声明

本项目仅供学习与研究使用，不构成任何投资建议。历史回测表现不代表未来收益。
