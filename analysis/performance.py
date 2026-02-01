import pandas as pd
import numpy as np
import backtrader as bt


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

    def generate_report(self):
        """生成并打印绩效报告，返回 self 供后续可视化"""
        metrics = self.get_metrics_summary()
        print("\n📊 绩效报告")
        print("-" * 40)
        for k, v in metrics.items():
            print(f"  {k}: {v}")
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
