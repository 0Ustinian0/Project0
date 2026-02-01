"""数据加载：从 CSV 目录加载并生成 Backtrader feeds"""
import os
import pandas as pd
import backtrader as bt


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


def load_data_into_cerebro(cerebro, data_dir, from_date, to_date, universe_size=None, logger=None):
    """
    将 data_dir 下的 CSV 加载到 cerebro：SPY 作为 data0，其余按 universe_size 限制数量。
    """
    if not os.path.exists(data_dir):
        raise FileNotFoundError(f"数据目录不存在: {data_dir}")
    all_files = [f for f in os.listdir(data_dir) if f.endswith('.csv')]
    if 'SPY.csv' in all_files:
        add_csv_feed(cerebro, os.path.join(data_dir, 'SPY.csv'), 'SPY', from_date, to_date, logger)
        all_files.remove('SPY.csv')
    else:
        if logger:
            logger.warning("未找到 SPY.csv，大盘风控可能失效")
    target_files = all_files[:universe_size] if universe_size else all_files
    for filename in target_files:
        ticker = filename.split('.')[0]
        filepath = os.path.join(data_dir, filename)
        add_csv_feed(cerebro, filepath, ticker, from_date, to_date, logger)
    if logger:
        logger.info(f"📊 [数据] 装载完成。总计: {len(cerebro.datas)} 只 (含SPY)")
    return len(cerebro.datas)
