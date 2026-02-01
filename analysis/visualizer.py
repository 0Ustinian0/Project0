import os
import pandas as pd
import matplotlib.pyplot as plt


def plot_equity_curve(rets, benchmark_csv=None, save_path='equity_curve.png'):
    strat_cum = (1 + rets).cumprod()
    plt.figure(figsize=(12, 6))
    plt.plot(strat_cum.index, strat_cum.values, label='Strategy', color='#1f77b4', linewidth=1.5)
    if benchmark_csv and os.path.exists(benchmark_csv):
        try:
            spy_df = pd.read_csv(benchmark_csv, index_col=0, parse_dates=True)
            common_idx = strat_cum.index.intersection(spy_df.index)
            if not common_idx.empty:
                spy_df = spy_df.loc[common_idx]
                spy_cum = (1 + spy_df['Close'].pct_change().fillna(0)).cumprod()
                spy_cum = spy_cum / spy_cum.iloc[0] * strat_cum.iloc[0]
                plt.plot(spy_cum.index, spy_cum.values, label='Benchmark (SPY)', color='gray', linestyle='--', alpha=0.8)
        except Exception as e:
            print(f"⚠️ 无法加载基准数据: {e}")
    plt.title('Equity Curve: Strategy vs Benchmark')
    plt.legend(loc='upper left')
    plt.grid(True, alpha=0.3)
    plt.ylabel('Normalized Value')
    plt.savefig(save_path)
    print(f"📈 净值曲线已保存: {save_path}")
    plt.close()


def plot_drawdown(rets, save_path='drawdown.png'):
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
    print(f"📉 回撤图已保存: {save_path}")
    plt.close()
