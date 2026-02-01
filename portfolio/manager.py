from portfolio import risk


class PortfolioManager:
    def __init__(self, initial_capital, max_leverage=1.0, max_positions=10):
        self.initial_capital = initial_capital
        self.max_leverage = max_leverage
        self.max_positions = max_positions
        self.default_risk_per_trade = 0.02
        self.default_stop_atr_mult = 3.0

    def calculate_position_size(self, account_value, price, atr, method='risk_parity', **kwargs):
        if price <= 0:
            return 0
        risk_pct = kwargs.get('risk_pct', self.default_risk_per_trade)
        stop_mult = kwargs.get('stop_mult', self.default_stop_atr_mult)
        return risk.position_size(
            account_value, price, atr,
            method=method,
            max_positions=self.max_positions,
            max_leverage=self.max_leverage,
            risk_pct=risk_pct,
            stop_mult=stop_mult
        )

    def check_cash_availability(self, current_cash, estimated_cost):
        buffer = current_cash * 0.02
        return (current_cash - buffer) >= estimated_cost

    def get_max_purchasable(self, current_cash, price):
        if price <= 0:
            return 0
        return int(current_cash / price)

    def check_leverage_limit(self, total_value, new_position_value):
        return risk.check_leverage_limit(total_value, new_position_value, self.max_leverage)

    def get_rebalance_targets(self, current_positions, ideal_weights, account_value, price_map):
        orders = []
        for ticker, target_pct in ideal_weights.items():
            price = price_map.get(ticker)
            if not price:
                continue
            target_value = account_value * target_pct
            target_shares = int(target_value / price)
            current_shares = current_positions.get(ticker, 0)
            diff = target_shares - current_shares
            if diff != 0 and abs(diff * price) > 500:
                orders.append((ticker, diff))
        return orders
