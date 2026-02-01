"""
数据下载：S&P 500 全量 / 仅 SPY
用法:
  全量: python -m data.providers.manager
  仅SPY: python -m data.providers.manager --spy-only
"""
import os
import io
import argparse
import yfinance as yf
import pandas as pd
import requests

# 与 main 一致：S&P 500 数据目录
DATA_DIR = os.path.join('data', 'SP500')


def get_sp500_tickers():
    """从维基百科获取 S&P 500 成分股列表"""
    print("正在获取 S&P 500 成分股列表...")
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (Chrome/91.0.4472.124) Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        tables = pd.read_html(io.StringIO(response.text))
        tickers = tables[0]['Symbol'].tolist()
        tickers = [t.replace('.', '-') for t in tickers]
        print(f"✅ 获取成功，共 {len(tickers)} 只股票。")
        return tickers
    except Exception as e:
        print(f"❌ 获取列表失败: {e}")
        print("⚠️ 将使用默认备选列表...")
        return ['NVDA', 'AMD', 'TSLA', 'AAPL', 'MSFT', 'AMZN', 'GOOG', 'META', 'NFLX', 'PLTR', 'COIN', 'MARA']


def download_spy(start_date='2017-01-01', end_date='2026-02-01', data_dir=None):
    """仅下载 SPY 到指定目录（默认 data/SP500/）"""
    target_dir = data_dir or DATA_DIR
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
    print("正在单独下载 SPY 数据...")
    df = yf.download('SPY', start=start_date, end=end_date, auto_adjust=True, progress=False)
    if df.empty:
        print("❌ SPY 下载失败，无数据。")
        return
    out_path = os.path.join(target_dir, 'SPY.csv')
    df_formatted = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
    df_formatted.reset_index(inplace=True)
    df_formatted.to_csv(out_path, index=False, header=True)
    print(f"✅ SPY.csv 已保存至 {out_path}")


def download_data(tickers, start_date='2017-01-01', end_date='2026-01-01', data_dir=None):
    """批量下载数据并保存为 CSV"""
    target_dir = data_dir or DATA_DIR
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
    print(f"开始下载数据 ({start_date} 至 {end_date})...")
    print(f"目标股票数: {len(tickers)} (全量下载可能需要 5–10 分钟)")
    data = yf.download(tickers, start=start_date, end=end_date, group_by='ticker', auto_adjust=True, threads=True, progress=False)
    success_count = 0
    if len(tickers) == 1:
        ticker = tickers[0]
        try:
            if not data.empty:
                df_formatted = data[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
                df_formatted.reset_index(inplace=True)
                df_formatted.to_csv(os.path.join(target_dir, f"{ticker}.csv"), index=False, header=True)
                success_count += 1
        except Exception:
            pass
    else:
        for ticker in tickers:
            try:
                df = data[ticker].dropna()
                if len(df) < 200:
                    continue
                df_formatted = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
                df_formatted.reset_index(inplace=True)
                df_formatted.to_csv(os.path.join(target_dir, f"{ticker}.csv"), index=False, header=True)
                success_count += 1
            except Exception as e:
                print(f"⚠️ 处理 {ticker} 失败: {e}")
    print(f"🎉 下载完成！成功保存 {success_count} 只股票数据到 '{target_dir}/'")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='下载 S&P 500 或仅 SPY 数据')
    parser.add_argument('--spy-only', action='store_true', help='仅下载 SPY')
    parser.add_argument('--start', default='2017-01-01', help='起始日期')
    parser.add_argument('--end', default='2026-02-01', help='结束日期')
    args = parser.parse_args()
    if args.spy_only:
        download_spy(start_date=args.start, end_date=args.end)
    else:
        tickers = get_sp500_tickers()
        download_data(tickers, start_date=args.start, end_date=args.end)
