import glob
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from collections import defaultdict

# 避免图表中中文/特殊符号导致 "Glyph missing from font" 警告：使用英文标签
plt.rcParams['axes.unicode_minus'] = False

try:
    import seaborn as sns
    sns.set_theme(style='whitegrid')
    HAS_SEABORN = True
except ImportError:
    HAS_SEABORN = False


def load_benchmark_returns(benchmark_csv):
    """从 data 目录 SPY CSV 加载日收益率 Series，与 plot_equity_curve 格式一致。供 Beta/Alpha 分析使用。"""
    return _load_benchmark_returns(benchmark_csv)


def _load_benchmark_returns(benchmark_csv):
    """内部：从 data 目录 SPY CSV 加载日收益率 Series。"""
    if not benchmark_csv or not os.path.exists(benchmark_csv):
        return None
    try:
        spy_df = pd.read_csv(
            benchmark_csv,
            skiprows=3,
            header=None,
            names=['Date', 'Close', 'High', 'Low', 'Open', 'Volume'],
            parse_dates=[0],
            index_col=0
        )
        spy_df['Close'] = pd.to_numeric(spy_df['Close'], errors='coerce')
        spy_df = spy_df.dropna(subset=['Close'])
        return spy_df['Close'].pct_change().dropna()
    except Exception:
        return None


def plot_equity_curve(rets, benchmark_csv=None, save_path='equity_curve.png', logger=None):
    strat_cum = (1 + rets).cumprod()
    plt.figure(figsize=(12, 6))
    plt.plot(strat_cum.index, strat_cum.values, label='Strategy', color='#1f77b4', linewidth=1.5)
    if benchmark_csv and os.path.exists(benchmark_csv):
        try:
            # 与 data 目录 CSV 格式一致：前 3 行为表头，第 4 行起为 Date, Close, ...
            spy_df = pd.read_csv(
                benchmark_csv,
                skiprows=3,
                header=None,
                names=['Date', 'Close', 'High', 'Low', 'Open', 'Volume'],
                parse_dates=[0],
                index_col=0
            )
            spy_df['Close'] = pd.to_numeric(spy_df['Close'], errors='coerce')
            spy_df = spy_df.dropna(subset=['Close'])
            common_idx = strat_cum.index.intersection(spy_df.index)
            if not common_idx.empty:
                spy_df = spy_df.loc[common_idx]
                spy_cum = (1 + spy_df['Close'].pct_change().fillna(0)).cumprod()
                spy_cum = spy_cum / spy_cum.iloc[0] * strat_cum.iloc[0]
                plt.plot(spy_cum.index, spy_cum.values, label='Benchmark (SPY)', color='gray', linestyle='--', alpha=0.8)
        except Exception as e:
            (logger.warning if logger else print)(f"⚠️ 无法加载基准数据: {e}")
    plt.title('Equity Curve: Strategy vs Benchmark')
    plt.legend(loc='upper left')
    plt.grid(True, alpha=0.3)
    plt.ylabel('Normalized Value')
    plt.savefig(save_path)
    (logger.info if logger else print)(f"📈 净值曲线已保存: {save_path}")
    plt.close()


def plot_drawdown(rets, save_path='drawdown.png', logger=None):
    strat_cum = (1 + rets).cumprod()
    running_max = strat_cum.cummax()
    drawdown = (strat_cum - running_max) / running_max
    plt.figure(figsize=(12, 4))
    plt.fill_between(drawdown.index, drawdown, 0, color='red', alpha=0.3)
    plt.plot(drawdown.index, drawdown, color='red', linewidth=1, label='Drawdown')
    plt.title('Drawdown Underwater')
    plt.ylabel('Drawdown %')
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.savefig(save_path)
    (logger.info if logger else print)(f"📉 回撤图已保存: {save_path}")
    plt.close()


def plot_rolling_metrics(rets, window=252, save_path='rolling_metrics.png', logger=None):
    """
    绘制滚动夏普比率与滚动波动率（年化），用于识别策略在特定时期（如 2020 熔断、2022 熊市）的失效。
    """
    from .performance import compute_rolling_metrics
    rolling_sharpe, rolling_vol = compute_rolling_metrics(rets, window=window)
    if rolling_sharpe.empty or rolling_vol.empty:
        if logger:
            logger.warning("数据不足，无法绘制滚动指标")
        return
    fig, axes = plt.subplots(2, 1, figsize=(12, 6), sharex=True)
    axes[0].plot(rolling_sharpe.index, rolling_sharpe.values, color='#1f77b4', linewidth=1)
    axes[0].axhline(0, color='gray', linestyle='--', alpha=0.7)
    axes[0].set_ylabel('Rolling Sharpe (ann.)')
    axes[0].set_title(f'Rolling Sharpe (window={window}d)')
    axes[0].grid(True, alpha=0.3)
    axes[1].plot(rolling_vol.index, rolling_vol.values, color='#d62728', linewidth=1)
    axes[1].set_ylabel('Rolling Vol (ann.)')
    axes[1].set_title(f'Rolling Volatility (window={window}d)')
    axes[1].grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(save_path)
    (logger.info if logger else print)(f"📊 滚动指标图已保存: {save_path}")
    plt.close()


def plot_monthly_heatmap(rets, save_path='monthly_heatmap.png', logger=None):
    """
    月度收益热力图：年 × 月，一眼看出哪个月亏损最严重。
    """
    rets = pd.Series(rets).dropna()
    rets.index = pd.to_datetime(rets.index)
    if rets.empty:
        if logger:
            logger.warning("无收益数据，无法绘制月度热力图")
        return
    df = pd.DataFrame({'ret': rets, 'year': rets.index.year, 'month': rets.index.month})
    monthly = df.groupby(['year', 'month'])['ret'].sum()
    monthly = monthly.unstack(level='month')
    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    monthly.columns = [month_names[int(c) - 1] if 1 <= int(c) <= 12 else str(int(c)) for c in monthly.columns]
    if HAS_SEABORN:
        fig, ax = plt.subplots(figsize=(12, max(4, len(monthly) * 0.4)))
        sns.heatmap(monthly * 100, annot=True, fmt='.1f', cmap='RdYlGn', center=0, ax=ax,
                    cbar_kws={'label': 'Return %'}, linewidths=0.5)
        ax.set_title('Monthly Return Heatmap (%)')
        ax.set_xlabel('Month')
        ax.set_ylabel('Year')
    else:
        fig, ax = plt.subplots(figsize=(12, max(4, len(monthly) * 0.4)))
        im = ax.imshow(monthly.values * 100, aspect='auto', cmap='RdYlGn', vmin=-10, vmax=10)
        ax.set_xticks(range(len(monthly.columns)))
        ax.set_xticklabels(monthly.columns)
        ax.set_yticks(range(len(monthly.index)))
        ax.set_yticklabels(monthly.index)
        plt.colorbar(im, ax=ax, label='Return %')
        ax.set_title('Monthly Return Heatmap (%)')
    plt.tight_layout()
    plt.savefig(save_path)
    (logger.info if logger else print)(f"📊 月度热力图已保存: {save_path}")
    plt.close()


def _read_stock_csv(data_dir, ticker, start, end):
    """读取单只股票 CSV 的 OHLC，供买卖点图使用。返回 DataFrame 或 None。"""
    try:
        from data.manager import _read_csv_to_df
    except Exception:
        return None
    path = os.path.join(data_dir, f'{ticker}.csv')
    if not os.path.isfile(path):
        return None
    return _read_csv_to_df(path, start, end, min_bars=None)


def plot_trades_on_prices(strategy_instance, data_dir, save_dir='.', max_stocks=30, logger=None):
    """
    为每只出现交易的股票绘制价格走势图，并在图上标注买入（绿三角）、卖出（红三角）时间点。
    便于直观查看策略在哪些位置做了买卖。
    图表保存到 save_dir/trade_charts/{TICKER}_trades.png，最多绘制 max_stocks 只股票（按交易次数优先）。
    """
    orders = getattr(strategy_instance, '_executed_orders', None) or []
    if not orders:
        if logger:
            logger.warning("无成交记录，跳过买卖点图")
        return
    by_ticker = defaultdict(list)
    for o in orders:
        by_ticker[o['ticker']].append(o)
    # 按交易次数排序，优先画交易多的
    tickers = sorted(by_ticker.keys(), key=lambda t: len(by_ticker[t]), reverse=True)[:max_stocks]
    out_dir = os.path.join(save_dir, 'trade_charts')
    os.makedirs(out_dir, exist_ok=True)
    # 生成前清空旧图，避免上次回测的图残留
    for f in glob.glob(os.path.join(out_dir, '*.png')):
        try:
            os.remove(f)
        except OSError:
            pass
    log = lambda msg: (logger.info(msg) if logger else print(msg))
    for ticker in tickers:
        ticker_orders = by_ticker[ticker]
        dates = [o['date'] for o in ticker_orders]
        start = pd.Timestamp(min(dates)) - pd.Timedelta(days=30)
        end = pd.Timestamp(max(dates)) + pd.Timedelta(days=30)
        df = _read_stock_csv(data_dir, ticker, start, end)
        if df is None or df.empty:
            if logger:
                logger.debug(f"无法加载 {ticker} 价格数据，跳过")
            continue
        buy_dates = [o['date'] for o in ticker_orders if o['side'] == 'buy']
        buy_prices = [o['price'] for o in ticker_orders if o['side'] == 'buy']
        sell_dates = [o['date'] for o in ticker_orders if o['side'] == 'sell']
        sell_prices = [o['price'] for o in ticker_orders if o['side'] == 'sell']
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(df.index, df['Close'], color='#1f77b4', linewidth=1, label='Close')
        if buy_dates and buy_prices:
            ax.scatter(buy_dates, buy_prices, color='green', marker='^', s=80, zorder=5, label='Buy')
        if sell_dates and sell_prices:
            ax.scatter(sell_dates, sell_prices, color='red', marker='v', s=80, zorder=5, label='Sell')
        ax.set_title(f'{ticker} — Price with Buy/Sell Points')
        ax.set_ylabel('Price')
        ax.legend(loc='upper left')
        ax.grid(True, alpha=0.3)
        fig.autofmt_xdate()
        path = os.path.join(out_dir, f'{ticker}_trades.png')
        plt.savefig(path)
        plt.close()
    log(f"买卖点图已保存至 {out_dir}，共 {len(tickers)} 只股票")


def plot_beta_analysis(rets, benchmark_csv=None, save_path='beta_analysis.png', logger=None):
    """
    基准对冲分析：策略 vs SPY 散点 + 回归线，标注 Beta / Alpha。
    收益来自大盘（Beta）还是选股能力（Alpha）一目了然。
    """
    from .performance import compute_beta_alpha
    bench_rets = _load_benchmark_returns(benchmark_csv) if benchmark_csv else None
    if bench_rets is None or rets is None or len(rets) < 2:
        if logger:
            logger.warning("缺少策略或基准收益，无法绘制 Beta 分析")
        return
    rets = pd.Series(rets).dropna()
    rets.index = pd.to_datetime(rets.index)
    common = rets.index.intersection(bench_rets.index)
    if len(common) < 2:
        if logger:
            logger.warning("策略与基准重叠交易日不足")
        return
    s = rets.reindex(common).fillna(0)
    b = bench_rets.reindex(common).fillna(0)
    res = compute_beta_alpha(s, b)
    beta, alpha_ann, r2 = res['beta'], res['alpha_annualized'], res['r_squared']
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.scatter(b.values * 100, s.values * 100, alpha=0.4, s=8, color='#1f77b4')
    x_line = np.array([b.min(), b.max()])
    y_line = (beta * x_line + alpha_ann / 252) * 100
    ax.plot(x_line * 100, y_line, 'r-', linewidth=2, label=f'Regression (beta={beta:.2f})')
    ax.axhline(0, color='gray', linestyle='--', alpha=0.5)
    ax.axvline(0, color='gray', linestyle='--', alpha=0.5)
    ax.set_xlabel('SPY Daily Return (%)')
    ax.set_ylabel('Strategy Daily Return (%)')
    ax.set_title(f'Beta Analysis | beta={beta:.2f}  alpha(ann.)={alpha_ann:.2%}  R2={r2:.3f}')
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(save_path)
    (logger.info if logger else print)(f"📊 Beta 分析图已保存: {save_path}")
    plt.close()
