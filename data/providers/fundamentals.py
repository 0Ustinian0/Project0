"""
基本面数据获取：从 Yahoo Finance (yfinance) 拉取 PE/PB/ROE/营收增长/负债权益比，
并保存为 data_dir/fundamentals.csv，供 screener 基本面过滤使用。

用法:
  按 config 中 data_dir 与股票池: python main.py --download-fundamentals
  或直接指定目录与股票列表: python -m data.providers.fundamentals --data-dir data/SP500 --tickers AAPL,MSFT,GOOGL
"""
import os
import argparse
import yfinance as yf
import pandas as pd


# 与 data/manager.load_fundamentals 期望的列名一致
COLUMNS = ['Ticker', 'PE', 'PB', 'ROE', 'RevenueGrowth', 'DebtToEquity']


def _safe_float(v, default=None):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def fetch_one_fundamentals(ticker):
    """
    从 yfinance 拉取单只股票基本面。
    返回: dict with Ticker, PE, PB, ROE, RevenueGrowth, DebtToEquity；缺失为 None。
    """
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        # Yahoo: trailingPE, priceToBook, returnOnEquity, debtToEquity, revenueGrowth(可能为 %)
        pe = _safe_float(info.get('trailingPE') or info.get('forwardPE'))
        pb = _safe_float(info.get('priceToBook'))
        roe = _safe_float(info.get('returnOnEquity'))
        if roe is not None and roe > 1:
            roe = roe / 100.0  # yfinance 有时为 1.52 表示 152%，转为 0.15 形式
        debt_to_equity = _safe_float(info.get('debtToEquity'))
        rev_growth = _safe_float(info.get('revenueGrowth'))
        if rev_growth is not None and abs(rev_growth) > 1 and abs(rev_growth) <= 1000:
            rev_growth = rev_growth / 100.0  # 15 -> 0.15
        return {
            'Ticker': ticker,
            'PE': pe,
            'PB': pb,
            'ROE': roe,
            'RevenueGrowth': rev_growth,
            'DebtToEquity': debt_to_equity,
        }
    except Exception:
        return {c: (ticker if c == 'Ticker' else None) for c in COLUMNS}


def fetch_fundamentals(tickers, data_dir, max_tickers=None, verbose=True):
    """
    批量拉取基本面并保存为 data_dir/fundamentals.csv。
    tickers: 股票代码列表
    data_dir: 与 config 中 data_dir 一致（如 data/SP500）
    max_tickers: 最多拉取只数（用于快速测试），None 表示全部
    """
    if not tickers:
        if verbose:
            print("[!] 股票列表为空")
        return 0
    if max_tickers is not None and max_tickers > 0:
        tickers = tickers[:int(max_tickers)]
    os.makedirs(data_dir, exist_ok=True)
    out_path = os.path.join(data_dir, 'fundamentals.csv')
    rows = []
    n = len(tickers)
    for i, ticker in enumerate(tickers):
        if verbose and (i + 1) % 20 == 0:
            print(f"  已拉取 {i + 1}/{n} ...")
        row = fetch_one_fundamentals(ticker)
        rows.append(row)
    df = pd.DataFrame(rows, columns=COLUMNS)
    df.to_csv(out_path, index=False)
    if verbose:
        print(f"[OK] 基本面已保存: {out_path}，共 {len(df)} 只")
    return len(df)


def get_tickers_from_data_dir(data_dir):
    """从 data_dir 下已有 CSV 文件名推断股票列表（排除 SPY）。"""
    if not os.path.isdir(data_dir):
        return []
    files = [f for f in os.listdir(data_dir) if f.endswith('.csv')]
    tickers = [f.replace('.csv', '') for f in files if f != 'SPY.csv']
    return sorted(tickers)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='拉取基本面并保存为 fundamentals.csv')
    parser.add_argument('--data-dir', default='data/SP500', help='与 config 中 data_dir 一致')
    parser.add_argument('--tickers', default=None, help='逗号分隔股票代码，不填则从 data-dir 下 CSV 推断')
    parser.add_argument('--max', type=int, default=None, help='最多拉取只数（测试用）')
    args = parser.parse_args()
    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(',') if t.strip()]
    else:
        tickers = get_tickers_from_data_dir(args.data_dir)
    fetch_fundamentals(tickers, args.data_dir, max_tickers=args.max)
