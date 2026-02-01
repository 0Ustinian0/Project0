"""StockScreener 单元测试：给定造假 DataFrame，确认筛选结果符合预期"""
import pandas as pd
import pytest
from strategy.screener import StockScreener


def _fake_snapshot(rows):
    """构造筛选器所需的日频快照 DataFrame，index 为标的代码"""
    df = pd.DataFrame(rows)
    if "Symbol" in df.columns:
        df = df.set_index("Symbol")
    return df


class TestStockScreenerLiquidity:
    """流动性过滤：min_price, min_volume, min_dollar_vol"""

    def test_filter_liquidity_keeps_above_min_price(self):
        df = _fake_snapshot([
            {"Symbol": "A", "Close": 15.0, "Volume": 1000, "MA200": 12.0, "RSI": 50},
            {"Symbol": "B", "Close": 5.0, "Volume": 1000, "MA200": 4.0, "RSI": 50},
        ])
        screener = StockScreener(df)
        screener.filter_liquidity(min_price=10.0)
        result = screener.get_result()
        assert result == ["A"]
        assert "流动性过滤" in screener.logs[0]

    def test_filter_liquidity_min_volume(self):
        df = _fake_snapshot([
            {"Symbol": "A", "Close": 20.0, "Volume": 500, "MA200": 18.0, "RSI": 50},
            {"Symbol": "B", "Close": 20.0, "Volume": 0, "MA200": 18.0, "RSI": 50},
        ])
        screener = StockScreener(df)
        screener.filter_liquidity(min_price=10.0, min_volume=1)
        result = screener.get_result()
        assert result == ["A"]

    def test_filter_liquidity_min_dollar_vol(self):
        df = _fake_snapshot([
            {"Symbol": "A", "Close": 100.0, "Volume": 200_000, "MA200": 90.0, "RSI": 50},   # 20M
            {"Symbol": "B", "Close": 10.0, "Volume": 100_000, "MA200": 9.0, "RSI": 50},   # 1M
        ])
        screener = StockScreener(df)
        screener.filter_liquidity(min_price=5.0, min_dollar_vol=10_000_000)
        result = screener.get_result()
        assert result == ["A"]


class TestStockScreenerTrendAndRsi:
    """趋势与 RSI 过滤"""

    def test_filter_trend_alignment_keeps_above_ma200(self):
        df = _fake_snapshot([
            {"Symbol": "A", "Close": 110.0, "Volume": 1000, "MA200": 100.0, "RSI": 50},
            {"Symbol": "B", "Close": 90.0, "Volume": 1000, "MA200": 100.0, "RSI": 50},
        ])
        screener = StockScreener(df)
        screener.filter_liquidity(min_price=0).filter_trend_alignment()
        assert screener.get_result() == ["A"]

    def test_filter_rsi_setup_range(self):
        df = _fake_snapshot([
            {"Symbol": "A", "Close": 20.0, "Volume": 1000, "MA200": 18.0, "RSI": 60},
            {"Symbol": "B", "Close": 20.0, "Volume": 1000, "MA200": 18.0, "RSI": 80},
        ])
        screener = StockScreener(df)
        screener.filter_liquidity(min_price=0).filter_rsi_setup(max_rsi=75)
        result = screener.get_result()
        assert "A" in result
        assert "B" not in result


class TestStockScreenerRankAndCut:
    """排序与截断"""

    def test_rank_and_cut_top_n(self):
        df = _fake_snapshot([
            {"Symbol": "A", "Close": 20.0, "Volume": 1000, "MA200": 15.0, "RSI": 50, "PrevClose": 18.0, "ATR": 1.0},
            {"Symbol": "B", "Close": 22.0, "Volume": 1000, "MA200": 16.0, "RSI": 50, "PrevClose": 20.0, "ATR": 1.0},
            {"Symbol": "C", "Close": 21.0, "Volume": 1000, "MA200": 14.0, "RSI": 50, "PrevClose": 20.0, "ATR": 1.0},
        ])
        screener = StockScreener(df)
        screener.filter_liquidity(min_price=0).filter_trend_alignment().filter_rsi_setup()
        screener.rank_and_cut(top_n=2)
        result = screener.get_result()
        assert len(result) == 2
        # RelativeStrength = (Close - PrevClose) / ATR -> B=2, C=1, A=2
        assert "B" in result
        assert "A" in result or "C" in result

    def test_empty_after_filter_returns_empty_list(self):
        df = _fake_snapshot([
            {"Symbol": "A", "Close": 1.0, "Volume": 0, "MA200": 2.0, "RSI": 90},
        ])
        screener = StockScreener(df)
        screener.filter_liquidity(min_price=10.0, min_volume=1)
        result = screener.get_result()
        assert result == []
