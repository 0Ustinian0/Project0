"""PortfolioManager 单元测试：仓位计算在极端资金或 ATR 下不为负或无穷"""
import pytest
from portfolio.manager import PortfolioManager
from portfolio import risk


class TestPortfolioManagerPositionSize:
    """calculate_position_size：不为负、不为无穷"""

    @pytest.fixture
    def pm(self):
        return PortfolioManager(initial_capital=100_000, max_positions=10, max_leverage=1.0)

    def test_zero_price_returns_zero(self, pm):
        assert pm.calculate_position_size(100_000, 0, 2.0) == 0
        assert pm.calculate_position_size(100_000, -1, 2.0) == 0

    def test_zero_atr_risk_parity_returns_zero(self, pm):
        # risk_parity 依赖 ATR，ATR=0 应返回 0
        size = pm.calculate_position_size(100_000, 50.0, 0, method="risk_parity")
        assert size == 0

    def test_negative_atr_returns_non_negative(self, pm):
        # 历史实现可能用 atr 做分母产生负数，应被 clamp 为 0
        size = pm.calculate_position_size(100_000, 50.0, -1.0, method="risk_parity")
        assert size >= 0 and size != float("inf")

    def test_normal_risk_parity_positive_finite(self, pm):
        size = pm.calculate_position_size(100_000, 50.0, 2.0, method="risk_parity")
        assert size >= 0
        assert size != float("inf")
        assert size < 1_000_000  # 合理上界

    def test_extreme_capital_small_atr(self, pm):
        # 资金很大、ATR 很小 -> 单笔风险金额大，但应被 max_allocation 限制，且非负、有限
        size = pm.calculate_position_size(10_000_000, 100.0, 0.01, method="risk_parity")
        assert size >= 0
        assert size != float("inf")
        assert size < 1_000_000

    def test_equal_weight_extreme_price(self, pm):
        size = pm.calculate_position_size(100_000, 1e-6, 1.0, method="equal_weight")
        # 可能很大但应有限；若 price 过小导致 int 溢出，至少不应为负
        assert size >= 0
        assert size != float("inf")

    def test_fixed_fraction_positive(self, pm):
        size = pm.calculate_position_size(100_000, 50.0, 2.0, method="fixed_fraction", fixed_pct=0.1)
        assert size >= 0
        assert size != float("inf")


class TestRiskModulePositionSize:
    """直接测 risk.position_size 边界"""

    def test_position_size_never_negative(self):
        # 各种边界组合
        cases = [
            (0, 50, 2, "risk_parity"),
            (100_000, 0, 2, "risk_parity"),
            (100_000, 50, 0, "risk_parity"),
            (100_000, 50, -1, "risk_parity"),
            (100_000, -1, 2, "risk_parity"),
        ]
        for account_value, price, atr, method in cases:
            s = risk.position_size(account_value, price, atr, method=method)
            assert s >= 0, f"account_value={account_value}, price={price}, atr={atr} -> {s}"
            assert s != float("inf")
