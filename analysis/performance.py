import pandas as pd
import numpy as np
import backtrader as bt

# 年化因子（日频）
ANNUALIZE = np.sqrt(252)
ANNUALIZE_MEAN = 252


def report_from_returns(rets):
    """从收益序列生成绩效报告（用于多策略合并后的收益或任意 Series）。"""
    if rets is None or len(rets) == 0:
        print("  (无收益数据)")
        return
    rets = pd.Series(rets).dropna()
    rets.index = pd.to_datetime(rets.index)
    total_ret = (1 + rets).prod() - 1
    days = (rets.index[-1] - rets.index[0]).days
    years = days / 365.25 if days > 0 else 0
    cagr = (1 + total_ret) ** (1 / years) - 1 if years > 0 else 0
    volatility = rets.std() * np.sqrt(252) if len(rets) > 1 else 0
    sharpe = (rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0
    cum = (1 + rets).cumprod()
    running_max = cum.cummax()
    drawdown_pct = (cum - running_max) / running_max
    max_dd = drawdown_pct.min() * 100
    metrics = {
        "年化收益率 (CAGR)": f"{cagr:.2%}",
        "夏普比率 (Sharpe)": f"{sharpe:.2f}",
        "最大回撤 (MaxDD)": f"{max_dd:.2f}%",
        "年化波动率 (Vol)": f"{volatility:.2%}",
    }
    print("\n📊 绩效报告 (组合)")
    print("-" * 40)
    for k, v in metrics.items():
        print(f"  {k}: {v}")
    return metrics


class PerformanceAnalyzer:
    def __init__(self, strategy_instance):
        self.strat = strategy_instance
        self.analyzers = strategy_instance.analyzers
        if hasattr(self.analyzers, 'returns'):
            self.rets = pd.Series(self.analyzers.returns.get_analysis())
            self.rets.index = pd.to_datetime(self.rets.index)
        else:
            self.rets = pd.Series(dtype=float)

    def get_metrics_summary(self):
        sharpe = self.analyzers.sharpe.get_analysis().get('sharperatio', 0)
        dd_res = self.analyzers.drawdown.get_analysis()
        max_dd = dd_res.get('max', {}).get('drawdown', 0)
        if len(self.rets) > 0:
            total_ret = (1 + self.rets).prod() - 1
            days = (self.rets.index[-1] - self.rets.index[0]).days
            years = days / 365.25
            cagr = (1 + total_ret) ** (1 / years) - 1 if years > 0 else 0
            volatility = self.rets.std() * np.sqrt(252)
        else:
            cagr, volatility = 0, 0
        trade_analysis = self.analyzers.trades.get_analysis()
        total_closed = trade_analysis.get('total', {}).get('total', 0)
        won = trade_analysis.get('won', {}).get('total', 0)
        win_rate = (won / total_closed) if total_closed > 0 else 0
        return {
            "年化收益率 (CAGR)": f"{cagr:.2%}",
            "夏普比率 (Sharpe)": f"{(sharpe or 0):.2f}",
            "最大回撤 (MaxDD)": f"{max_dd:.2f}%",
            "年化波动率 (Vol)": f"{volatility:.2%}",
            "总交易次数": total_closed,
            "胜率 (Win Rate)": f"{win_rate:.2%}"
        }

    def generate_report(self, logger=None):
        """生成并打印绩效报告，返回 self 供后续可视化。logger 可选，用于统一输出。"""
        metrics = self.get_metrics_summary()
        out = lambda msg: (logger.info(msg) if logger else print(msg))
        out("\n📊 绩效报告")
        out("-" * 40)
        for k, v in metrics.items():
            out(f"  {k}: {v}")
        return self

    def get_attribution_analysis(self):
        ticker_stats = {}
        for data, trades in self.strat._trades.items():
            ticker = data._name
            if ticker not in ticker_stats:
                ticker_stats[ticker] = {'PnL': 0.0, 'Trades': 0, 'Wins': 0}
            for trade in trades:
                if not hasattr(trade, 'status'):
                    continue
                if trade.status == trade.Closed:
                    pnl = getattr(trade, 'pnlcomm', 0) or 0
                    ticker_stats[ticker]['PnL'] += pnl
                    ticker_stats[ticker]['Trades'] += 1
                    if pnl > 0:
                        ticker_stats[ticker]['Wins'] += 1
        for data, pos in self.strat.broker.positions.items():
            if pos.size != 0:
                ticker = data._name
                if ticker not in ticker_stats:
                    ticker_stats[ticker] = {'PnL': 0.0, 'Trades': 0, 'Wins': 0}
                open_pnl = (data.close[0] - pos.price) * pos.size
                ticker_stats[ticker]['PnL'] += open_pnl
        results = []
        for ticker, stats in ticker_stats.items():
            win_rate = stats['Wins'] / stats['Trades'] if stats['Trades'] > 0 else 0
            results.append({
                'Ticker': ticker,
                'Total PnL': stats['PnL'],
                'Trades': stats['Trades'],
                'Win Rate': win_rate
            })
        df = pd.DataFrame(results)
        if not df.empty:
            df = df.sort_values(by='Total PnL', ascending=False)
        return df


def compute_rolling_metrics(rets, window=252):
    """
    计算滚动夏普比率和滚动波动率（年化）。
    rets: 日收益率 Series，index 为日期。
    window: 滚动窗口（交易日），默认 252 ≈ 1 年。
    返回: (rolling_sharpe, rolling_vol)，均为 Series。
    """
    rets = pd.Series(rets).dropna()
    rets.index = pd.to_datetime(rets.index)
    if len(rets) < window:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    roll_mean = rets.rolling(window).mean()
    roll_std = rets.rolling(window).std()
    rolling_vol = (roll_std * ANNUALIZE).dropna()
    rolling_sharpe = (roll_mean / roll_std * ANNUALIZE).replace([np.inf, -np.inf], np.nan).dropna()
    return rolling_sharpe, rolling_vol


def compute_beta_alpha(strat_rets, bench_rets, risk_free_daily=0.0):
    """
    计算策略相对基准的 Beta 与 Alpha（CAPM）。
    strat_rets, bench_rets: 日收益率 Series，需对齐到共同交易日。
    risk_free_daily: 日无风险利率，默认 0。
    返回: dict with beta, alpha_annualized, r_squared。
    """
    strat_rets = pd.Series(strat_rets).dropna()
    bench_rets = pd.Series(bench_rets).dropna()
    common = strat_rets.index.intersection(bench_rets.index)
    if len(common) < 2:
        return {'beta': 0.0, 'alpha_annualized': 0.0, 'r_squared': 0.0}
    s = strat_rets.reindex(common).fillna(0) - risk_free_daily
    b = bench_rets.reindex(common).fillna(0) - risk_free_daily
    cov_sb = s.cov(b)
    var_b = b.var()
    if var_b == 0:
        beta = 0.0
    else:
        beta = cov_sb / var_b
    alpha_daily = s.mean() - beta * b.mean()
    alpha_annualized = alpha_daily * ANNUALIZE_MEAN
    # R²: 回归解释的方差比例
    pred = beta * b
    ss_res = ((s - pred) ** 2).sum()
    ss_tot = ((s - s.mean()) ** 2).sum()
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
    return {'beta': float(beta), 'alpha_annualized': float(alpha_annualized), 'r_squared': float(r_squared)}


def get_beta_alpha_summary(strat_rets, bench_rets):
    """
    计算策略相对基准的 Beta / Alpha，返回可打印的指标 dict。
    bench_rets 可由调用方从 SPY CSV 加载；若无基准则返回空 dict。
    """
    if bench_rets is None or strat_rets is None or len(strat_rets) < 2:
        return {}
    res = compute_beta_alpha(strat_rets, bench_rets)
    return {
        "Beta (vs SPY)": f"{res['beta']:.2f}",
        "Alpha (年化)": f"{res['alpha_annualized']:.2%}",
        "R²": f"{res['r_squared']:.3f}",
    }
