"""RiskManager / 止损逻辑单元测试：确认止损条件是否被正确触发"""
import pytest
from portfolio import risk


class TestShouldTriggerStopLoss:
    """should_trigger_stop_loss(close, highest_price, atr, stop_atr_mult)"""

    def test_trigger_when_below_stop_line(self):
        # 止损线 = 100 - 2*3 = 94，现价 93 < 94 -> 应触发
        assert risk.should_trigger_stop_loss(93.0, 100.0, 2.0, 3.0) is True

    def test_no_trigger_when_above_stop_line(self):
        assert risk.should_trigger_stop_loss(95.0, 100.0, 2.0, 3.0) is False

    def test_trigger_exactly_at_stop_line(self):
        # 现价 = 94 等于止损线，严格 < 才触发，所以 94 < 94 为 False
        assert risk.should_trigger_stop_loss(94.0, 100.0, 2.0, 3.0) is False

    def test_trigger_when_just_below(self):
        assert risk.should_trigger_stop_loss(93.99, 100.0, 2.0, 3.0) is True

    def test_atr_zero_never_triggers(self):
        assert risk.should_trigger_stop_loss(0.0, 100.0, 0.0, 3.0) is False

    def test_atr_negative_never_triggers(self):
        assert risk.should_trigger_stop_loss(50.0, 100.0, -1.0, 3.0) is False

    def test_atr_none_never_triggers(self):
        assert risk.should_trigger_stop_loss(50.0, 100.0, None, 3.0) is False

    def test_different_multiplier(self):
        # stop = 100 - 5*2 = 90
        assert risk.should_trigger_stop_loss(89.0, 100.0, 5.0, 2.0) is True
        assert risk.should_trigger_stop_loss(91.0, 100.0, 5.0, 2.0) is False
