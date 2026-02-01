import math

class PortfolioManager:
    def __init__(self, initial_capital, max_leverage=1.0, max_positions=10):
        """
        :param initial_capital: 初始资金 (主要用于记录基准，实际计算用动态净值)
        :param max_leverage: 最大杠杆率 (1.0 表示不加杠杆)
        :param max_positions: 最大持仓只数
        """
        self.initial_capital = initial_capital
        self.max_leverage = max_leverage
        self.max_positions = max_positions
        
        # 风险参数默认值
        self.default_risk_per_trade = 0.02  # 单笔交易风险 2%
        self.default_stop_atr_mult = 3.0    # 默认 3倍 ATR 止损

    # ==========================================
    # 1. 仓位计算 (Position Sizing)
    # ==========================================
    def calculate_position_size(self, account_value, price, atr, method='risk_parity', **kwargs):
        """
        核心功能：计算应该买多少股
        :param method: 'risk_parity'(风险平价/ATR), 'equal_weight'(等权), 'fixed_fraction'(固定比例)
        """
        if price <= 0: return 0

        # 获取参数，如果没有则使用默认值
        risk_pct = kwargs.get('risk_pct', self.default_risk_per_trade)
        stop_mult = kwargs.get('stop_mult', self.default_stop_atr_mult)

        target_shares = 0

        # --- A. 风险平价模型 (Risk Parity / Volatility Sizing) ---
        # 逻辑：波动越大的股票，买得越少。让每笔交易的潜在亏损固定为总资金的 N%
        if method == 'risk_parity':
            if atr <= 0: return 0
            
            risk_amount = account_value * risk_pct      # 愿意亏多少钱 (比如 10万 * 2% = 2000)
            stop_distance = atr * stop_mult             # 止损距离 (比如 ATR=5 * 3 = 15元)
            
            if stop_distance > 0:
                target_shares = int(risk_amount / stop_distance)

        # --- B. 等权重模型 (Equal Weight) ---
        # 逻辑：将资金平均分配给 N 只股票
        elif method == 'equal_weight':
            allocation_pct = 1.0 / self.max_positions # 比如 10只，每只 10%
            target_value = account_value * allocation_pct * self.max_leverage
            target_shares = int(target_value / price)

        # --- C. 固定比例模型 (Fixed Fraction) ---
        # 逻辑：不管有多少只股，每只都买总资金的固定百分比 (比如 20%)
        elif method == 'fixed_fraction':
            fixed_pct = kwargs.get('fixed_pct', 0.10)
            target_value = account_value * fixed_pct
            target_shares = int(target_value / price)

        # --- 统一风控截断 ---
        # 1. 资金上限保护：单只股票绝对不能超过账户总值的 30% (防止低波动股买太多)
        max_allocation = account_value * 0.30
        if target_shares * price > max_allocation:
            target_shares = int(max_allocation / price)

        return target_shares

    # ==========================================
    # 2. 现金管理 (Cash Management)
    # ==========================================
    def check_cash_availability(self, current_cash, estimated_cost):
        """
        检查是否有足够现金买入
        """
        # 预留 2% 的现金作为缓冲 (应对滑点或手续费)
        buffer = current_cash * 0.02
        if current_cash - buffer >= estimated_cost:
            return True
        return False

    def get_max_purchasable(self, current_cash, price):
        """
        根据现金计算最大可买股数
        """
        if price <= 0: return 0
        return int(current_cash / price)

    # ==========================================
    # 3. 杠杆控制 (Leverage Control)
    # ==========================================
    def check_leverage_limit(self, total_value, new_position_value):
        """
        检查开新仓后是否会爆仓/超杠杆
        """
        current_exposure = total_value # 假设当前市值就是敞口 (无做空情况下)
        # 这里实际上很难在策略层精确获知"未成交订单"的占用，只能估算
        # 如果是简单的做多策略，总市值 / 净值 不能超过 max_leverage
        
        projected_leverage = (total_value + new_position_value) / total_value
        # 注意：Backtrader 的 total_value 已经包含了持仓市值。
        # 如果是用现金买入，总敞口增加，但 total_value 不变。
        # 这里简化为：不允许 总持仓市值 > 净值 * 杠杆
        
        return True # 在 Backtrader 现金账户模式下，通常很难超过 1.0，除非用融资

    # ==========================================
    # 4. 再平衡逻辑 (Rebalancing)
    # ==========================================
    def get_rebalance_targets(self, current_positions, ideal_weights, account_value, price_map):
        """
        计算再平衡的目标股数
        :param current_positions: 字典 {ticker: shares}
        :param ideal_weights: 字典 {ticker: target_percent} (如 {'AAPL': 0.1})
        :param price_map: 字典 {ticker: current_price}
        """
        orders = []
        
        for ticker, target_pct in ideal_weights.items():
            price = price_map.get(ticker)
            if not price: continue
            
            target_value = account_value * target_pct
            target_shares = int(target_value / price)
            
            current_shares = current_positions.get(ticker, 0)
            diff = target_shares - current_shares
            
            if diff != 0:
                # 设置一个最小交易门槛，比如变动小于 $500 就不动，节省手续费
                if abs(diff * price) > 500: 
                    orders.append((ticker, diff)) # 正数买入，负数卖出
                    
        return orders