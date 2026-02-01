# 补全 SPY 数据脚本
import yfinance as yf
import os

if not os.path.exists('data'):
    os.makedirs('data')

print("正在单独下载 SPY 数据...")
df = yf.download('SPY', start='2017-01-01', end='2026-02-01', auto_adjust=True)
df.to_csv('data/SPY.csv')
print("✅ SPY.csv 下载完成！")