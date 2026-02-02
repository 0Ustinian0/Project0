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
            roc126 = inds[d]['roc126'][0] if 'roc126' in inds[d] else float('nan')
        except (IndexError, KeyError, TypeError):
            continue
        close, prev_close, atr = d.close[0], d.close[-1], inds[d]['atr'][0]
        atr_pct = (close - prev_close) / atr if atr and atr > 0 else 0.0  # 短期爆发(ATR涨幅)
        snapshot_data.append({
            'Ticker': d._name,
            'Close': close,
            'PrevClose': prev_close,
            'Volume': d.volume[0],
            'Volume_MA20': inds[d]['vol_ma'][0],
            'MA20': inds[d]['ma20'][0] if 'ma20' in inds[d] else float('nan'),
            'MA50': inds[d]['ma50'][0],
            'MA150': inds[d]['ma150'][0],
            'MA200': inds[d]['ma200'][0],
            'RSI': inds[d]['rsi'][0],
            'ATR': atr,
            '52W_High': inds[d]['high52'][0],
            '52W_Low': inds[d]['low52'][0],
            'ROC_126': roc126,
            'ATR_pct': atr_pct,
        })
    if not snapshot_data:
        return pd.DataFrame()
    return pd.DataFrame(snapshot_data).set_index('Ticker')
