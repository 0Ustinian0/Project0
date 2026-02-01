# 回测流程：配置 → 数据 → 选股 → 策略 → 引擎 → 运行 → 分析 → 可视化
import pandas as pd
from run.imports import (
    os,
    bt,
    ConfigLoader,
    BacktestEngine,
    ModularScreenerStrategy,
    PerformanceAnalyzer,
    plot_equity_curve,
    plot_drawdown,
    plot_rolling_metrics,
    plot_monthly_heatmap,
    plot_beta_analysis,
    report_from_returns,
    get_beta_alpha_summary,
    load_benchmark_returns,
    get_sp500_tickers,
    download_data,
    download_spy,
    UNIVERSE_NAME,
    DEFAULT_DATA_DIR,
)
from engine.optimizer import (
    select_final_params,
    walk_forward_analysis,
    validate_parameter_selection,
    run_bayesian_optimization,
    compute_composite_score,
    _extract_metric,
)
from utils.logger import Logger, PREFIX_CONFIG, PREFIX_DATA, PREFIX_OPTIM, PREFIX_ENGINE, PREFIX_ANALYSIS, PREFIX_VALID

# 多策略：名称 -> 策略类，便于 yaml 中写 name: screener
STRATEGY_REGISTRY = {"screener": ModularScreenerStrategy}


def make_cerebro_factory(data, fixed_params=None):
    """返回 (start, end, strategy_cls, params) -> cerebro，用于 WFA / 多窗口验证。"""
    def factory(start, end, strategy_cls, params):
        full = {**fixed_params, **params} if fixed_params else params
        data_w = {**data, 'from_date': start, 'to_date': end}
        engine = BacktestEngine(
            data=data_w,
            strategy=strategy_cls,
            strategy_params=full,
            initial_capital=data['initial_capital'],
            commission=data['commission'],
            slippage=data['slippage'],
        )
        return engine.cerebro
    return factory


def _run_single_backtest_metric(data, strategy_cls, params, metric):
    """单次回测并返回指定指标（供贝叶斯优化调用）。"""
    engine = BacktestEngine(
        data=data,
        strategy=strategy_cls,
        strategy_params=params,
        initial_capital=data['initial_capital'],
        commission=data['commission'],
        slippage=data['slippage'],
    )
    result = engine.run()
    return _extract_metric(result, metric)


def load_config():
    """加载配置（回测参数 + 策略参数 + 优化/多策略）"""
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
        'optimization': loader.get_optimization_config(),
        'multi_strategy': loader.get_multi_strategy_config(),
        'logging': loader.get_logging_config(),
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
        'universe_seed': bt_config.get('universe_seed'),
        'initial_capital': bt_config['initial_capital'],
        'commission': bt_config['commission'],
        'slippage': bt_config.get('slippage', 0.0),
    }


def get_stock_universe(data):
    """从数据目录获取股票池列表（供引擎加载；实际选股在策略内逐日筛选）。universe_seed 用于可复现随机子集。"""
    data_dir = data['data_dir']
    if not os.path.isdir(data_dir):
        return []
    files = sorted([f for f in os.listdir(data_dir) if f.endswith('.csv')])
    if 'SPY.csv' in files:
        files.remove('SPY.csv')
    universe_size = data.get('universe_size')
    universe_seed = data.get('universe_seed')
    if universe_size is not None and universe_size > 0:
        if universe_seed is not None:
            import random
            rng = random.Random(universe_seed)
            files = files.copy()
            rng.shuffle(files)
        files = files[:universe_size]
    return [f.replace('.csv', '') for f in files]


def analyze_results(strategy_instance):
    """分析回测结果，返回 PerformanceAnalyzer 实例"""
    return PerformanceAnalyzer(strategy_instance)


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


def download_fundamentals(config, max_tickers=None):
    """按 config 中 data_dir 拉取当前股票池的基本面并保存为 fundamentals.csv（yfinance）。"""
    from data.providers.fundamentals import fetch_fundamentals, get_tickers_from_data_dir
    data_dir = config.get('data_dir') or config.get('bt', {}).get('data_dir')
    if not data_dir:
        print("[!] 未找到 data_dir 配置")
        return
    tickers = get_tickers_from_data_dir(data_dir)
    if not tickers:
        print("[!] 未在 data_dir 下找到股票 CSV，请先运行 python main.py --download 或放入 CSV")
        return
    fetch_fundamentals(tickers, data_dir, max_tickers=max_tickers)


def run_optimization(config, data):
    """参数优化：grid | walk_forward | bayesian，可选多窗口验证。"""
    opt = config.get('optimization', {})
    param_grid = opt.get('param_grid', {})
    if not param_grid:
        log = Logger()
        log.warning("optimization.param_grid 为空，请配置至少一组参数列表（如 atr_period: [10, 14, 20]）")
        return
    metric = opt.get('metric', 'sharperatio')
    maximize = opt.get('maximize', True)
    merged_params = {**config['strategy'], **param_grid}
    grid_only = {k: v for k, v in param_grid.items() if isinstance(v, (list, tuple)) and not isinstance(v, str)}
    fixed_params = {k: v for k, v in merged_params.items() if k not in grid_only}
    method = opt.get('method', 'grid')

    best_params, best_value, all_results = None, None, []
    log = Logger()

    if method == 'grid':
        composite_weights = opt.get('composite_weights')
        engine = BacktestEngine(
            data=data,
            strategy=None,
            initial_capital=data['initial_capital'],
            commission=data['commission'],
            slippage=data['slippage'],
        )
        best_params, best_value, all_results = engine.run_optimization(
            ModularScreenerStrategy,
            param_grid=merged_params,
            metric=metric,
            maximize=maximize,
            composite_weights=composite_weights if (metric and str(metric).lower() == 'composite') else None,
        )
        if metric and str(metric).lower() == 'composite' and composite_weights and all_results and isinstance(all_results[0][1], dict):
            all_results = compute_composite_score(all_results, composite_weights, maximize=maximize)
            best_params = all_results[0][0] if all_results else None
            best_value = all_results[0][1] if all_results else None
        log.section("参数优化结果 (网格搜索)")
    elif method == 'walk_forward':
        train_days = int(opt.get('walk_forward_train_days', 252))
        test_days = int(opt.get('walk_forward_test_days', 63))
        cerebro_factory = make_cerebro_factory(data, fixed_params)
        best_params, best_value, wfa_results = walk_forward_analysis(
            cerebro_factory,
            ModularScreenerStrategy,
            grid_only,
            train_days,
            test_days,
            data['from_date'],
            data['to_date'],
            data.get('data_dir'),
            data.get('universe_size'),
            metric=metric,
            maximize=maximize,
            logger=log,
        )
        all_results = [(p, v) for p, v, _ in wfa_results]
        print("\n🔬 参数优化结果 (Walk-Forward)")
    elif method == 'bayesian':
        n_calls = int(opt.get('bayesian_n_calls', 50))
        run_backtest = lambda p: _run_single_backtest_metric(data, ModularScreenerStrategy, p, metric)
        best_params, best_value = run_bayesian_optimization(
            grid_only,
            fixed_params,
            run_backtest,
            n_calls=n_calls,
            maximize=maximize,
            logger=log,
        )
        all_results = [(best_params, best_value)] if best_params else []
        log.section("参数优化结果 (贝叶斯优化)")
    else:
        log.warning(f"未知 optimization.method: {method}，使用 grid")
        method = 'grid'
        engine = BacktestEngine(
            data=data,
            strategy=None,
            initial_capital=data['initial_capital'],
            commission=data['commission'],
            slippage=data['slippage'],
        )
        best_params, best_value, all_results = engine.run_optimization(
            ModularScreenerStrategy,
            param_grid=merged_params,
            metric=metric,
            maximize=maximize,
        )

    # 最终参数：grid/walk_forward 可再经 plateau/robust 等选择；bayesian 直接用最优
    if method == 'bayesian' or not all_results:
        final_params, final_metric = best_params or {}, best_value
    else:
        final_method = opt.get('final_params_method', 'best')
        plateau_top_pct = float(opt.get('plateau_top_pct', 0.2))
        plateau_threshold = opt.get('plateau_threshold')  # 若设置，则用阈值筛选优秀组合替代 top_pct
        if plateau_threshold is not None:
            plateau_threshold = float(plateau_threshold)
        robust_alpha = float(opt.get('robust_alpha', 0.7))
        robust_radius = int(opt.get('robust_radius', 1))
        n_clusters = int(opt.get('n_clusters', 3))
        grid_candidates = grid_only or None
        final_params, final_metric = select_final_params(
            all_results,
            method=final_method,
            top_pct=plateau_top_pct,
            maximize=maximize,
            grid_candidates=grid_candidates,
            robust_alpha=robust_alpha,
            robust_radius=robust_radius,
            n_clusters=n_clusters,
            plateau_threshold=plateau_threshold,
        )

    print("-" * 50)
    print(f"  目标指标: {metric} (maximize={maximize})")
    print(f"  单点最优: {best_params} -> {best_value}")
    print(f"  最终参数: {final_params} -> {final_metric}")
    if all_results and len(all_results) <= 20:
        print("  全部组合:")
        for i, (params, val) in enumerate(all_results[:10]):
            print(f"    {i+1}. {params} -> {val}")

    if opt.get('run_final_backtest', True) and final_params:
        print("\n📌 使用最终参数运行回测并输出结果...")
        engine_final = BacktestEngine(
            data=data,
            strategy=ModularScreenerStrategy,
            strategy_params=final_params,
            initial_capital=data['initial_capital'],
            commission=data['commission'],
            slippage=data['slippage'],
        )
        result = engine_final.run()
        if result is not None:
            analyzer = PerformanceAnalyzer(result)
            report = analyzer.generate_report(log)
            visualize_results(report, data['data_dir'], logger=log)
        log.info("  推荐参数（可复制到 config/settings.yaml 的 strategy 下）:")
        for k, v in sorted(final_params.items()):
            log.info(f"    {k}: {v}")

    if opt.get('run_validation', False) and final_params:
        train_days = int(opt.get('walk_forward_train_days', 252))
        test_days = int(opt.get('walk_forward_test_days', 63))
        cerebro_factory = make_cerebro_factory(data)
        report = validate_parameter_selection(
            cerebro_factory,
            ModularScreenerStrategy,
            final_params,
            train_days,
            test_days,
            data['from_date'],
            data['to_date'],
            metric=metric,
            logger=log,
        )
        print("\n📐 多时间窗口/样本外验证")
        print("-" * 50)
        print(f"  窗口数: {len(report['per_window'])}")
        print(f"  {metric} 均值: {report['mean']}")
        print(f"  {metric} 标准差: {report['std']}")
        if report['per_window']:
            for start, end, val in report['per_window'][:5]:
                print(f"    窗口 {start.date()} ~ {end.date()}: {val}")

    return final_params, final_metric, all_results


def run_multi_strategy(config, data):
    """多策略并行：各策略按权重分配资金独立运行，再合并收益曲线。"""
    multi = config.get('multi_strategy', {})
    strategies_cfg = multi.get('strategies', [])
    log = Logger()
    if not strategies_cfg:
        log.warning("multi_strategy.strategies 为空")
        return
    total_capital = data['initial_capital']
    returns_list = []
    weights = []
    for item in strategies_cfg:
        name = item.get('name', 'screener')
        params = item.get('params', {})
        weight = float(item.get('weight', 1.0 / len(strategies_cfg)))
        strat_cls = STRATEGY_REGISTRY.get(name, ModularScreenerStrategy)
        capital = total_capital * weight
        engine = BacktestEngine(
            data=data,
            strategy=strat_cls,
            strategy_params=params,
            initial_capital=capital,
            commission=data['commission'],
            slippage=data['slippage'],
        )
        result = engine.run()
        if result is not None and hasattr(result, 'analyzers') and hasattr(result.analyzers, 'returns'):
            ret_dict = result.analyzers.returns.get_analysis()
            ret_series = pd.Series(ret_dict)
            ret_series.index = pd.to_datetime(ret_series.index)
            returns_list.append(ret_series)
    if not returns_list:
        print("⚠️ 无有效策略收益")
        return
    # 对齐日期：并集，缺失填 0
    all_index = returns_list[0].index
    for r in returns_list[1:]:
        all_index = all_index.union(r.index)
    blended = pd.Series(0.0, index=all_index)
    used_weights = weights[:len(returns_list)]
    for ret_series, w in zip(returns_list, used_weights):
        blended = blended.add(ret_series.reindex(all_index).fillna(0) * w, fill_value=0)
    report_from_returns(blended)
    visualize_results(None, data['data_dir'], rets_override=blended)


def visualize_results(report, data_dir, rets_override=None, logger=None):
    """生成净值曲线、回撤图、滚动指标、月度热力图、Beta 分析。若 rets_override 有值则用其作为收益序列（多策略合并时）。"""
    benchmark_csv = os.path.join(data_dir, 'SPY.csv')
    rets = rets_override if rets_override is not None else (report.rets if report is not None and hasattr(report, 'rets') else None)
    if rets is None or (hasattr(rets, 'empty') and rets.empty):
        if logger:
            logger.warning("无收益数据，跳过可视化")
        return
    out = lambda msg: (logger.info(msg) if logger else print(msg))
    plot_equity_curve(rets, benchmark_csv=benchmark_csv, logger=logger)
    plot_drawdown(rets, logger=logger)
    plot_rolling_metrics(rets, window=252, save_path='rolling_metrics.png', logger=logger)
    plot_monthly_heatmap(rets, save_path='monthly_heatmap.png', logger=logger)
    plot_beta_analysis(rets, benchmark_csv=benchmark_csv, save_path='beta_analysis.png', logger=logger)
    bench_rets = load_benchmark_returns(benchmark_csv)
    beta_summary = get_beta_alpha_summary(rets, bench_rets)
    if beta_summary:
        out("\n📊 基准对冲 (vs SPY)")
        out("-" * 40)
        for k, v in beta_summary.items():
            out(f"  {k}: {v}")


def main(force_optimize=False, force_multi_strategy=False):
    # 1. 初始化配置
    config = load_config()
    log_cfg = config.get('logging') or {}
    log = Logger(
        log_dir=log_cfg.get('log_dir', 'logs'),
        file_name=log_cfg.get('file_name'),
        retain_count=log_cfg.get('retain_count', 10),
        quiet_console_init=log_cfg.get('quiet_console_init', False),
    )
    log.info(f"{PREFIX_CONFIG} 配置已加载 | 数据源: {config['universe']} ({config['data_dir']})")

    # 2. 数据准备
    data = prepare_data(config)

    # 3. 筛选股票池（获取待加载标的列表；策略内 Screener 逐日筛选）
    stock_universe = get_stock_universe(data)
    log.info(f"{PREFIX_DATA} 数据目录下共 {len(stock_universe)} 只标的可加载")

    if force_optimize or config.get('optimization', {}).get('enabled'):
        run_optimization(config, data)
        return

    if force_multi_strategy or config.get('multi_strategy', {}).get('enabled'):
        run_multi_strategy(config, data)
        return

    # 4. 单策略回测
    strategy = ModularScreenerStrategy
    params = config['strategy']
    log.info(f"{PREFIX_CONFIG} 策略参数: {params}")

    engine = BacktestEngine(
        data=data,
        strategy=strategy,
        strategy_params=params,
        initial_capital=data['initial_capital'],
        commission=data['commission'],
        slippage=data['slippage'],
    )
    results = engine.run()
    analyzer = PerformanceAnalyzer(results)
    report = analyzer.generate_report(log)
    visualize_results(report, data['data_dir'], logger=log)
