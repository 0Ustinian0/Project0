# 回测流程：配置 → 数据 → 选股 → 策略 → 引擎 → 运行 → 分析 → 可视化
from run.imports import (
    os,
    bt,
    ConfigLoader,
    BacktestEngine,
    ModularScreenerStrategy,
    PerformanceAnalyzer,
    plot_equity_curve,
    plot_drawdown,
    get_sp500_tickers,
    download_data,
    download_spy,
    UNIVERSE_NAME,
    DEFAULT_DATA_DIR,
)


def load_config():
    """加载配置（回测参数 + 策略参数）"""
    loader = ConfigLoader()
    bt_config = loader.get_backtest_config()
    strat_config = loader.get_strategy_config()
    data_dir = bt_config.get('data_dir', DEFAULT_DATA_DIR)
    universe = bt_config.get('universe', UNIVERSE_NAME)
    return {
        'bt': bt_config,
        'strategy': strat_config,
        'data_dir': data_dir,
        'universe': universe,
    }


def prepare_data(config):
    """数据准备：从配置生成引擎所需的数据规格（目录、日期、资金、成本等）"""
    bt_config = config['bt']
    data_dir = config['data_dir']
    return {
        'data_dir': data_dir,
        'from_date': bt_config['start_date'],
        'to_date': bt_config['end_date'],
        'universe_size': bt_config.get('universe_size'),
        'initial_capital': bt_config['initial_capital'],
        'commission': bt_config['commission'],
        'slippage': bt_config.get('slippage', 0.0),
    }


def get_stock_universe(data):
    """从数据目录获取股票池列表（供引擎加载；实际选股在策略内逐日筛选）"""
    data_dir = data['data_dir']
    if not os.path.isdir(data_dir):
        return []
    files = [f for f in os.listdir(data_dir) if f.endswith('.csv')]
    universe_size = data.get('universe_size')
    if universe_size is not None and universe_size > 0:
        files = files[:universe_size]
    return [f.replace('.csv', '') for f in files]


def analyze_results(strategy_instance):
    """分析回测结果，返回 PerformanceAnalyzer 实例"""
    return PerformanceAnalyzer(strategy_instance)


def visualize_results(report, data_dir):
    """生成净值曲线与回撤图"""
    benchmark_csv = os.path.join(data_dir, 'SPY.csv')
    plot_equity_curve(report.rets, benchmark_csv=benchmark_csv)
    plot_drawdown(report.rets)


def _date_str(dt):
    """datetime -> YYYY-MM-DD"""
    return dt.strftime('%Y-%m-%d') if hasattr(dt, 'strftime') else str(dt)[:10]


def download_all(config):
    """按配置下载 S&P 500 全量数据（使用 config 中的 data_dir 与日期）"""
    bt_config = config['bt']
    data_dir = config['data_dir']
    start = _date_str(bt_config.get('start_date', '2017-01-01'))
    end = _date_str(bt_config.get('end_date', '2026-02-01'))
    tickers = get_sp500_tickers()
    download_data(tickers, start_date=start, end_date=end, data_dir=data_dir)


def download_spy_only(config):
    """按配置仅下载 SPY（使用 config 中的 data_dir 与日期）"""
    bt_config = config['bt']
    data_dir = config['data_dir']
    start = _date_str(bt_config.get('start_date', '2017-01-01'))
    end = _date_str(bt_config.get('end_date', '2026-02-01'))
    download_spy(start_date=start, end_date=end, data_dir=data_dir)


def main():
    # 1. 初始化配置
    config = load_config()
    print(f"⚙️ 配置已加载 | 数据源: {config['universe']} ({config['data_dir']})")

    # 2. 数据准备
    data = prepare_data(config)

    # 3. 筛选股票池（获取待加载标的列表；策略内 Screener 逐日筛选）
    stock_universe = get_stock_universe(data)
    print(f"📂 数据目录下共 {len(stock_universe)} 只标的可加载")

    # 4. 初始化策略（策略类 + 参数，由引擎注入）
    strategy = ModularScreenerStrategy
    params = config['strategy']
    print(f"🧠 策略参数: {params}")

    # 5. 初始化回测引擎
    engine = BacktestEngine(
        data=data,
        strategy=strategy,
        strategy_params=params,
        initial_capital=data['initial_capital'],
        commission=data['commission'],
        slippage=data['slippage'],
    )

    # 6. 运行回测
    results = engine.run()

    # 7. 分析结果
    analyzer = PerformanceAnalyzer(results)
    report = analyzer.generate_report()

    # 8. 可视化
    visualize_results(report, data['data_dir'])
