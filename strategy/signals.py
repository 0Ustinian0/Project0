"""信号与快照构建：供 strategy 调用"""
import math
import pandas as pd


def build_snapshot(datas, spy, inds):
    """
    从 Backtrader datas 构建当日全市场快照 DataFrame。
    :param datas: self.datas
    :param spy: self.spy (跳过)
    :param inds: self.inds[d] 指标字典
    :return: DataFrame, index=Ticker, columns=Close, PrevClose, Volume, Volume_MA20, MA50, MA150, MA200, RSI, ATR, 52W_High, 52W_Low
    """
    snapshot_data = []
    for d in datas:
        if d is spy:
            continue
        if d not in inds:
            continue
        try:
            if math.isnan(inds[d]['ma200'][0]):
                continue
        except (IndexError, KeyError, TypeError):
            continue
        snapshot_data.append({
            'Ticker': d._name,
            'Close': d.close[0],
            'PrevClose': d.close[-1],
            'Volume': d.volume[0],
            'Volume_MA20': inds[d]['vol_ma'][0],
            'MA50': inds[d]['ma50'][0],
            'MA150': inds[d]['ma150'][0],
            'MA200': inds[d]['ma200'][0],
            'RSI': inds[d]['rsi'][0],
            'ATR': inds[d]['atr'][0],
            '52W_High': inds[d]['high52'][0],
            '52W_Low': inds[d]['low52'][0],
        })
    if not snapshot_data:
        return pd.DataFrame()
    return pd.DataFrame(snapshot_data).set_index('Ticker')
