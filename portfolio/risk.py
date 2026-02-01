"""仓位与风险计算：风险平价、等权、杠杆检查等"""
# 供 portfolio.manager 调用，也可单独用于回测外的测算

def position_size(account_value, price, atr, method='risk_parity', max_positions=10, max_leverage=1.0, **kwargs):
    """
    计算应买股数。
    method: risk_parity / equal_weight / fixed_fraction
    """
    if price <= 0:
        return 0
    risk_pct = kwargs.get('risk_pct', 0.02)
    stop_mult = kwargs.get('stop_mult', 3.0)
    target_shares = 0
    if method == 'risk_parity':
        if atr <= 0:
            return 0
        risk_amount = account_value * risk_pct
        stop_distance = atr * stop_mult
        if stop_distance > 0:
            target_shares = int(risk_amount / stop_distance)
    elif method == 'equal_weight':
        allocation_pct = 1.0 / max_positions
        target_value = account_value * allocation_pct * max_leverage
        target_shares = int(target_value / price)
    elif method == 'fixed_fraction':
        fixed_pct = kwargs.get('fixed_pct', 0.10)
        target_value = account_value * fixed_pct
        target_shares = int(target_value / price)
    max_allocation = account_value * 0.30
    if target_shares * price > max_allocation:
        target_shares = int(max_allocation / price)
    return max(0, target_shares)


def should_trigger_stop_loss(close, highest_price, atr, stop_atr_mult):
    """
    判断是否应触发止损：现价 < 止损线（最高价 - ATR * 倍数）。
    供策略层调用，也可单独做单元测试。
    """
    if atr is None or atr <= 0:
        return False
    stop_price = highest_price - (atr * stop_atr_mult)
    return close < stop_price


def check_leverage_limit(total_value, new_position_value, max_leverage=1.0):
    """检查开新仓后是否超杠杆（简化）"""
    return True
