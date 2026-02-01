# Project0 — 股票回测框架

基于 Backtrader 的模块化股票回测系统，支持 S&P 500 选股、策略回测、绩效分析与净值/回撤可视化。

## 功能概览

- **配置驱动**：通过 `config/settings.yaml` 设置回测区间、资金、佣金、滑点及策略参数
- **数据**：支持从 Yahoo Finance 下载 S&P 500 全量或仅 SPY，数据存放在 `data/SP500/`
- **策略**：选股 + 趋势过滤（如 MA200）+ 入场/出场规则，可配置持仓数、风险比例等
- **回测引擎**：Backtrader 驱动，支持佣金、滑点、夏普/回撤/交易分析
- **分析**：绩效报告（CAGR、夏普、最大回撤、胜率等）、净值曲线图、回撤图

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
│   ├── backtest.py      # BacktestEngine（Cerebro 封装）
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
```

## 环境与依赖

- Python 3.8+
- 主要依赖：`backtrader`、`pandas`、`numpy`、`matplotlib`、`pyyaml`、`yfinance`、`requests`

安装示例：

```bash
pip install backtrader pandas numpy matplotlib pyyaml yfinance requests
```

## 使用方法

### 1. 配置

编辑 `config/settings.yaml`：

- **backtest**：`universe`、`data_dir`、`universe_size`（如 50 做快速测试）、`initial_capital`、`commission`、`slippage`、`start_date`、`end_date`
- **strategy**：`max_pos`、`risk_per_trade_pct`、`lookback_period`、`entry_threshold`、`exit_threshold`、`min_price`、`min_dollar_vol` 等

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
