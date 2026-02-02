# Project0 — 股票回测框架

基于 Backtrader 的模块化股票回测系统，支持 S&P 500 选股、策略回测、绩效分析与净值/回撤可视化。

## 功能概览

- **配置驱动**：通过 `config/settings.yaml` 设置回测区间、资金、佣金、滑点及策略参数
- **数据**：支持从 Yahoo Finance 下载 S&P 500 全量或仅 SPY，数据存放在 `data/SP500/`
- **策略**：选股 + 趋势过滤（如 MA200）+ 入场/出场规则，可配置持仓数、风险比例等
- **回测引擎**：Backtrader 驱动，支持佣金、滑点、夏普/回撤/交易分析
- **分析**：绩效报告（CAGR、夏普、最大回撤、胜率等）、净值曲线图、回撤图
- **数据验证**：加载 CSV 前校验 OHLC 逻辑（如 High < Low、缺失值、全 0）、避免脏数据导致策略崩溃
- **单元测试**：基于 pytest 对选股、仓位、止损与数据验证做单测，修改核心逻辑后可快速回归

## 项目结构

```
├── main.py              # 入口：回测 / 下载数据
├── config/
│   ├── settings.yaml    # 回测与策略配置
│   └── loader.py        # 配置加载
├── run/
│   ├── flow.py          # 回测流程：配置→数据→选股→策略→引擎→分析→可视化
│   └── imports.py       # 集中导入
├── data/
│   ├── SP500/           # 股票 CSV（按 config 中 data_dir）
│   ├── manager.py       # 数据加载进 Cerebro
│   └── providers/       # S&P 500 列表与 yfinance 下载
├── strategy/
│   ├── strategy.py      # 主策略（选股 + 指标 + 下单）
│   ├── screener.py      # 选股过滤（流动性、趋势、RSI 等）
│   ├── signals.py       # 信号与快照
│   └── order_manager.py # 下单管理
├── engine/
│   ├── backtest.py      # BacktestEngine（Cerebro 封装 + 网格优化）
│   ├── optimizer.py     # 网格搜索 / Walk-Forward 分析
│   └── simulator.py     # 模拟相关
├── portfolio/
│   ├── manager.py       # 持仓与资金管理
│   └── risk.py          # 风险控制
├── analysis/
│   ├── performance.py   # 绩效统计与报告
│   └── visualizer.py    # 净值曲线、回撤图
└── utils/
    ├── logger.py        # 日志
    └── helpers.py       # 工具函数
├── tests/               # 单元测试（pytest）
│   ├── test_screener.py
│   ├── test_portfolio_manager.py
│   ├── test_risk.py
│   └── test_data_validation.py
```

## 环境与依赖

- Python 3.8+
- 主要依赖：`backtrader`、`pandas`、`numpy`、`matplotlib`、`pyyaml`、`yfinance`、`requests`

安装示例：

```bash
pip install backtrader pandas numpy matplotlib pyyaml yfinance requests
```

运行单元测试需额外安装：`pip install -r requirements-dev.txt`（或 `pip install pytest`）。

## 使用方法

### 1. 配置

编辑 `config/settings.yaml`：

- **backtest**：`universe`、`data_dir`、`universe_size`（如 50 做快速测试）、`initial_capital`、`commission`、`slippage`、`start_date`、`end_date`
- **strategy**：`max_pos`、`risk_per_trade_pct`、`lookback_period`、`entry_threshold`、`exit_threshold`、`min_price`、`min_dollar_vol` 等
- **基本面过滤（可选）**：在 `data_dir` 下放置 `fundamentals.csv`，并在 strategy 中设 `fundamentals_enabled: true`。CSV 可含：`Ticker, PE, PB, ROE, RevenueGrowth, DebtToEquity, Sector, EPS_Growth`（PE 估值、EPS_Growth 盈利增长 % 或小数、Sector 板块）。screener 支持 **估值过滤**（0<PE≤max_pe）、**成长过滤**（EPS_Growth≥min_eps_growth）、**板块过滤**（Sector=sector_name）；`sector`/`min_eps_growth` 不设则不筛。提高 `top_n`（如 8）可增加每日候选数以提升交易量。

**基本面数据从哪里取得**

- **本项目（推荐）**：使用 Yahoo Finance 拉取 PE/PB/ROE/营收增长/负债权益比，自动写入 `data_dir/fundamentals.csv`。先确保 `data_dir` 下已有股票 CSV（如已运行过 `--download`），再执行：
  ```bash
  python main.py --download-fundamentals
  ```
  或指定目录与股票列表：`python -m data.providers.fundamentals --data-dir data/SP500 --tickers AAPL,MSFT,GOOGL`；`--max 20` 可限制只拉取前 20 只（测试用）。
- **其他免费/付费来源**：  
  - [Financial Modeling Prep (FMP)](https://site.financialmodelingprep.com/)：API 提供 PE/PB/ROE 等，有免费额度。  
  - [Alpha Vantage](https://www.alphavantage.co/)：免费 API 含部分基本面。  
  - [Yahoo Finance](https://finance.yahoo.com/)：网页手动导出或第三方库（本项目已用 yfinance）。  
- **手动**：从财报或财经网站整理成 `Ticker, PE, PB, ROE, RevenueGrowth, DebtToEquity` 的 CSV，放入 `data_dir/fundamentals.csv`。可参考 `data/SP500/fundamentals.csv.example`。

### 2. 下载数据（可选）

- 下载 S&P 500 全量数据（使用 config 中的日期与目录）：
  ```bash
  python main.py --download
  ```
- 仅下载 SPY：
  ```bash
  python main.py --download-spy
  ```

### 3. 运行回测

不传参数时默认执行回测：

```bash
python main.py
```

流程：加载配置 → 准备数据 → 获取股票池 → 初始化策略与引擎 → 运行回测 → 生成绩效报告 → 输出净值曲线与回撤图（默认 `equity_curve.png`、`drawdown.png`）。

### 4. 参数优化与最终参数接入

运行 `python main.py --optimize` 时，由 `optimization.method` 选择优化方式：

- **grid**（默认）：网格搜索，对 `param_grid` 笛卡尔积逐一回测，按 `metric` 排序；再经 `final_params_method`（best / plateau / plateau_kde / cluster / robust）确定最终参数。

**稳健绩效指标**（`optimization.metric`）：除夏普、净值、回撤外，支持 **Calmar**（CAGR/|MaxDD|）、**Sortino**（下行波动率调整收益）、**win_rate**（胜率）、**profit_factor**（盈亏比）、**cagr**（年化收益）。设置 **metric: composite** 并配置 **composite_weights** 可对多个指标加权归一化得到综合得分，平衡收益与风险（如 `sharperatio: 0.3, calmar: 0.3, win_rate: 0.2, profit_factor: 0.2`）；`drawdown` 参与综合时自动按“越低越好”处理。
- **walk_forward**：向前步进分析。按 `walk_forward_train_days` / `walk_forward_test_days` 滚动划分训练/测试窗口，对每组参数在测试段上评估，按各窗口指标均值排序；同样可再经 plateau/robust 等选最终参数。
- **bayesian**：贝叶斯优化（需 `pip install scikit-optimize`）。在由 `param_grid` 导出的参数空间上用高斯过程优化，迭代 `bayesian_n_calls` 次，直接得到最优参数。

**最终参数选择**（仅 grid / walk_forward 时生效）：`final_params_method` 可为 best、plateau、**plateau_freq**、plateau_kde、cluster、robust。**plateau_freq**（改进 Plateau）：先取绩效排名前 `plateau_top_pct` 或按 `plateau_threshold`（指标 ≥/≤ 某值）筛选优秀组合，对每个参数计算这些组合中的**频率分布**，取**出现频率最高的值**作为该参数；若该值不在网格上则取最近的网格值；若合成组合不在结果中则取网格距离最近的有效组合。

**接入结果**：若 `run_final_backtest: true`（默认），会用最终参数再跑一次全区间回测，输出绩效报告与净值/回撤图，并打印「推荐参数」供复制到 `strategy` 下。

**多时间窗口/样本外验证**：若 `run_validation: true`，在选定最终参数后，会在多个滚动窗口的测试段上回测，输出该指标在各窗口的均值、标准差及每窗口结果，用于评估参数稳健性。

可选依赖：`plateau_kde` 建议 `scipy`；`cluster` 建议 `scikit-learn`；`method: bayesian` 需 `scikit-optimize`。

配置示例（片段）：

```yaml
optimization:
  method: grid          # grid | walk_forward | bayesian（CLI --optimize-wfa / --optimize-bayesian 可覆盖）
  metric: sharperatio
  maximize: true
  composite_preset: null # balanced | aggressive | conservative（metric=composite 时三选一，方便使用）
  # 每参数：列表=参与优化，null/false=不优化（用 strategy 默认）
  param_grid:
    atr_period: [10, 14, 20]
    rsi_period: [10, 14]
    risk_per_trade_pct: [0.02, 0.03, 0.04]
    stop_atr_mult: [3.0, 3.5, 4.0]
    vol_multiplier: null   # 不优化；改为 [0.6, 0.8, 1.0] 即参与优化
  max_combos: 36        # 组合数上限，超过则随机抽样，避免跑太久
  random_state: 42
  walk_forward_train_days: 252
  walk_forward_test_days: 63
  bayesian_n_calls: 25  # 贝叶斯迭代次数，不宜过大
  final_params_method: cluster
  plateau_top_pct: 0.2
  robust_alpha: 0.7
  robust_radius: 1
  n_clusters: 3
  run_final_backtest: true
  run_validation: false
```

### 5. 单元测试

修改 `screener.py`、`portfolio/manager.py`、`portfolio/risk.py` 等核心逻辑后，可跑单测确认未破坏原有行为。

安装测试依赖并运行：

```bash
pip install -r requirements-dev.txt
# 或：pip install pytest
python -m pytest tests\ -v
```

重点覆盖：

- **StockScreener**：给定造假 DataFrame，验证流动性（min_price / min_volume / min_dollar_vol）、趋势（>MA200）、RSI 区间、排序截断 Top N 等筛选结果是否符合预期。
- **PortfolioManager**：`calculate_position_size` 在极端资金或 ATR（如 price=0、ATR=0、负 ATR）下不会算出负数或无穷大。
- **RiskManager / 止损**：`portfolio.risk.should_trigger_stop_loss(close, highest_price, atr, stop_atr_mult)` 是否在现价低于止损线时触发、ATR 无效时不触发。
- **数据验证**：`validate_data` 对空数据、High < Low、Close 超出 [Low,High]、缺列、OHLC 全为 0 等情况的报错与通过条件。

### 6. 数据清洗与验证

若下载的 CSV 某天数据全为 0，或存在 **High < Low**，策略可能崩溃或产生错误信号。在 `data/manager.py` 中增加了 **数据验证层**，在将数据加入 Cerebro 前统一校验。

`validate_data(df, strict=True)` 会：

- **检查缺失值**：存在 NaN 且 `strict=True` 时抛出 `ValueError`。
- **检查逻辑错误**：存在 **High < Low** 或 **Close 超出 [Low, High]** 时抛出 `ValueError`。
- **检查缺列**：缺少 Open / High / Low / Close / Volume 任一列时抛出。
- **停牌**：成交量为 0 的行仅打印警告，不抛错。
- **OHLC 全为 0**：`strict=True` 时抛出，避免“某天全为 0”的脏数据进入回测。

加载单只股票 CSV 的 `add_csv_feed` 会在加入 cerebro 前调用 `validate_data(df, strict=True)`，从源头拦截脏数据。

## 策略简述

- **择时**：SPY 收盘价在 MA200 上方才允许交易，否则当日不交易（熊市保护）。
- **选股**：流动性过滤（价格、成交量、成交额）、趋势过滤（收盘 > MA200）、RSI 等，由 `StockScreener` 完成。
- **入场/出场**：基于策略参数中的阈值与风控（如单笔风险比例、最大持仓数），由 `OrderManager` 与 `PortfolioManager` 执行。

更细的逻辑见 `strategy/strategy.py`、`strategy/screener.py`。

## 输出说明

- **终端**：配置信息、股票池数量、策略参数、回测起止资金、绩效报告（CAGR、夏普、最大回撤、波动率、交易次数、胜率）。
- **图片**：`equity_curve.png`（策略 vs SPY 净值）、`drawdown.png`（回撤曲线）。
- **日志**：可在 `utils/logger` 与 `logs/` 中查看（若已启用文件日志）。

## 许可证

本项目仅供学习与自用，不构成任何投资建议。
