"""数据验证层单元测试：validate_data 行为"""
import pandas as pd
import pytest
from data.manager import validate_data


def _ohlc_df(rows):
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close", "Volume"])


class TestValidateDataBasic:
    def test_valid_df_passes(self):
        df = _ohlc_df([
            [100, 105, 99, 102, 1_000_000],
            [102, 106, 101, 104, 1_100_000],
        ])
        assert validate_data(df, strict=True) is True

    def test_empty_raises(self):
        df = pd.DataFrame()
        with pytest.raises(ValueError, match="数据为空"):
            validate_data(df, strict=True)

    def test_none_raises(self):
        with pytest.raises(ValueError, match="数据为空"):
            validate_data(None, strict=True)


class TestValidateDataHighLow:
    def test_high_less_than_low_raises(self):
        df = _ohlc_df([
            [100, 95, 99, 98, 1_000_000],  # High=95 < Low=99
        ])
        with pytest.raises(ValueError, match="High < Low"):
            validate_data(df, strict=True)


class TestValidateDataCloseRange:
    def test_close_above_high_raises(self):
        df = _ohlc_df([
            [100, 105, 99, 110, 1_000_000],  # Close 110 > High 105
        ])
        with pytest.raises(ValueError, match="Close 超出"):
            validate_data(df, strict=True)

    def test_close_below_low_raises(self):
        df = _ohlc_df([
            [100, 105, 99, 98, 1_000_000],  # Close 98 < Low 99
        ])
        with pytest.raises(ValueError, match="Close 超出"):
            validate_data(df, strict=True)


class TestValidateDataMissingColumns:
    def test_missing_required_column_raises(self):
        df = pd.DataFrame({"Open": [100], "High": [105], "Low": [99], "Close": [102]})  # no Volume
        with pytest.raises(ValueError, match="缺少必需列"):
            validate_data(df, strict=True)


class TestValidateDataZeroOhlc:
    def test_all_zero_ohlc_raises_in_strict(self):
        df = _ohlc_df([
            [0, 0, 0, 0, 1000],
        ])
        with pytest.raises(ValueError, match="OHLC 全为 0"):
            validate_data(df, strict=True)
