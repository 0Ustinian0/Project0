"""数据加载：从 CSV 目录加载并生成 Backtrader feeds"""
import os
import pandas as pd
import backtrader as bt


def validate_data(df, strict=True):
    """
    数据验证层：检查缺失值、逻辑错误（High < Low）、停牌（成交量为 0）等。
    strict=True 时发现严重错误会 raise；否则仅打印警告。
    """
    if df is None or df.empty:
        raise ValueError("数据为空")

    # 检查缺失值
    if df.isnull().values.any():
        msg = "警告：发现缺失数据"
        if strict:
            raise ValueError(msg)
        if hasattr(validate_data, "_warned_null"):
            pass
        else:
            print(msg)

    # 必需列
    required = ['Open', 'High', 'Low', 'Close', 'Volume']
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"缺少必需列: {missing}")

    # 检查逻辑错误：High < Low
    if (df['High'] < df['Low']).any():
        raise ValueError("数据错误：存在 High < Low 的行情")

    # 检查 Close 是否在 [Low, High] 内
    if (df['Close'] > df['High']).any() or (df['Close'] < df['Low']).any():
        raise ValueError("数据错误：Close 超出 High/Low 范围")

    # 检查停牌（成交量为 0）：仅警告
    zero_vol = (df['Volume'] == 0).sum()
    if zero_vol > 0:
        print(f"警告：发现 {zero_vol} 行成交量为 0（可能停牌）")

    # 检查全 0 行（某天数据全为 0）
    ohlc_zero = ((df['Open'] == 0) & (df['High'] == 0) & (df['Low'] == 0) & (df['Close'] == 0))
    if ohlc_zero.any():
        if strict:
            raise ValueError("数据错误：存在 OHLC 全为 0 的行情")
        print("警告：存在 OHLC 全为 0 的行情")

    return True


def add_csv_feed(cerebro, filepath, name, start, end, logger=None):
    """
    读取单只股票 CSV，转换为 PandasData 并加入 cerebro。
    兼容格式：skiprows=3, 列为 Date, Close, High, Low, Open, Volume。
    """
    try:
        df = pd.read_csv(
            filepath,
            skiprows=3,
            header=None,
            names=['Date', 'Close', 'High', 'Low', 'Open', 'Volume'],
            parse_dates=[0],
            index_col=0
        )
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(subset=['Open', 'High', 'Low', 'Close', 'Volume'])
        df = df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
        if len(df) == 0:
            return False
        validate_data(df, strict=True)
        data = bt.feeds.PandasData(
            dataname=df,
            name=name,
            fromdate=start,
            todate=end,
            open='Open', high='High', low='Low', close='Close', volume='Volume',
            openinterest=None
        )
        cerebro.adddata(data)
        return True
    except Exception as e:
        if logger:
            logger.warning(f"加载 {name} 失败: {e}")
        return False


def load_data_into_cerebro(cerebro, data_dir, from_date, to_date, universe_size=None, universe_seed=None, logger=None):
    """
    将 data_dir 下的 CSV 加载到 cerebro：SPY 作为 data0，其余按 universe_size 限制数量。
    universe_seed 有值时，对股票列表排序后按种子 shuffle 再取前 N，保证可复现。
    """
    if not os.path.exists(data_dir):
        raise FileNotFoundError(f"数据目录不存在: {data_dir}")
    all_files = sorted([f for f in os.listdir(data_dir) if f.endswith('.csv')])
    if 'SPY.csv' in all_files:
        add_csv_feed(cerebro, os.path.join(data_dir, 'SPY.csv'), 'SPY', from_date, to_date, logger)
        all_files.remove('SPY.csv')
    else:
        if logger:
            logger.warning("未找到 SPY.csv，大盘风控可能失效")
    if universe_size is not None and universe_size > 0:
        if universe_seed is not None:
            import random
            rng = random.Random(universe_seed)
            all_files = all_files.copy()
            rng.shuffle(all_files)
        target_files = all_files[:universe_size]
    else:
        target_files = all_files
    for filename in target_files:
        ticker = filename.split('.')[0]
        filepath = os.path.join(data_dir, filename)
        add_csv_feed(cerebro, filepath, ticker, from_date, to_date, logger)
    if logger:
        logger.info(f"📊 [数据] 装载完成。总计: {len(cerebro.datas)} 只 (含SPY)")
    return len(cerebro.datas)


def load_fundamentals(data_dir, logger=None):
    """
    从 data_dir/fundamentals.csv 加载基本面数据（可选）。
    CSV 格式：Ticker, PE, PB, ROE, RevenueGrowth, DebtToEquity
    - PE/PB: 市盈率/市净率，空或负表示亏损或无效，过滤时可跳过
    - ROE/RevenueGrowth: 小数形式，如 0.15 表示 15%
    - DebtToEquity: 负债/权益，空则不过滤
    返回: DataFrame index=Ticker, columns=pe,pb,roe,revenue_growth,debt_to_equity；无文件或失败返回 None。
    """
    if not data_dir or not os.path.exists(data_dir):
        return None
    path = os.path.join(data_dir, 'fundamentals.csv')
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, dtype=str)
        df = df.rename(columns=lambda c: c.strip().lower().replace(' ', '_'))
        col_map = {'ticker': 'Ticker', 'pe': 'PE', 'pb': 'PB', 'roe': 'ROE',
                   'revenue_growth': 'RevenueGrowth', 'revenuegrowth': 'RevenueGrowth',
                   'debt_to_equity': 'DebtToEquity', 'debttoequity': 'DebtToEquity'}
        for k, v in col_map.items():
            if k in df.columns and v not in df.columns:
                df[v] = df[k]
        if 'Ticker' not in df.columns and 'ticker' in df.columns:
            df['Ticker'] = df['ticker']
        numeric_cols = ['PE', 'PB', 'ROE', 'RevenueGrowth', 'DebtToEquity']
        for c in numeric_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce')
        df = df.set_index('Ticker')
        keep = [c for c in numeric_cols if c in df.columns]
        df = df[keep] if keep else df
        if logger:
            logger.debug(f"基本面数据已加载: {path}, {len(df)} 只")
        return df
    except Exception as e:
        if logger:
            logger.warning(f"加载基本面文件失败 {path}: {e}")
        return None
