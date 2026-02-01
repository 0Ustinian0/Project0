import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt

# 1. 下载 SPY 数据 (对应你的回测时间段)
print("正在下载 SPY 数据用于绘图...")
spy = yf.download('SPY', start='2020-01-01', end='2026-02-01', progress=False)

# 处理 MultiIndex 列（yfinance 有时会返回 MultiIndex）
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.droplevel(1)

# 2. 计算 200日均线
spy['MA200'] = spy['Close'].rolling(window=200).mean()

# 3. 绘图
plt.figure(figsize=(15, 8))

# 画股价和均线
plt.plot(spy.index, spy['Close'], label='SPY Price', color='black', alpha=0.6)
plt.plot(spy.index, spy['MA200'], label='MA 200 (Bull/Bear Line)', color='red', linewidth=2)

# --- 区域 A: 200天预热期 (灰色) ---
# 这一段时间因为 MA200 还没算出来 (NaN)，策略无法判断，所以强制空仓
warmup_period = spy[spy['MA200'].isna()]
if len(warmup_period) > 0:
    plt.axvspan(warmup_period.index[0], warmup_period.index[-1], 
                color='gray', alpha=0.3, label='Warmup Period (No Data for MA200)')

# --- 区域 B: 熊市避险期 (红色) ---
# 价格 < 均线，策略自动停止买入
bear_market = spy[spy['Close'] < spy['MA200']]
# 为了画图好看，我们不用 fill_between，而是简单标记
# 这里使用 fill_between 填充所有 价格 < 均线 的区域
plt.fill_between(spy.index, spy['Close'], spy['MA200'], 
                 where=(spy['Close'] < spy['MA200']), 
                 color='red', alpha=0.2, label='Bear Market Filter (Stop Buying)')

# --- 区域 C: 牛市交易期 (绿色) ---
# 价格 > 均线，策略正常工作
plt.fill_between(spy.index, spy['Close'], spy['MA200'], 
                 where=(spy['Close'] > spy['MA200']), 
                 color='green', alpha=0.1, label='Bull Market (Active Trading)')

plt.title('Strategy Regime Analysis: Why No Trades Initially?', fontsize=16)
plt.legend(loc='upper left')
plt.grid(True, alpha=0.3)
plt.show()