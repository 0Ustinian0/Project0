# strategies.py (修复版：解决了 TypeError 问题)
import backtrader as bt
import datetime
import math 

class GapUpStrategy(bt.Strategy):
    params = (
        ('max_pos', 10),
        ('risk_per_trade_pct', 0.03),
        
        # 筛选参数
        ('min_price', 10.0),
        ('atr_period', 14),
        ('vol_multiplier', 0.8),    
        ('jump_threshold_atr', 0.5), 
        ('stop_loss_atr', 3.0),
        ('rsi_threshold', 70), 
        
        # --- DEBUG 开关 ---
        ('debug_verbose', True) 
    )

    def __init__(self):
        self.inds = {}
        self.orders = {}      
        self.spy = self.datas[0] 
        
        self.spy_ma200 = bt.indicators.SMA(self.spy.close, period=200)

        # 记录策略启动的第一天
        self.first_run = True

        for d in self.datas:
            # 【修复点 1】必须用 'is' 而不是 '=='
            if d is self.spy: continue
            
            self.inds[d] = {
                'sma200': bt.indicators.SMA(d.close, period=200),
                'atr': bt.indicators.ATR(d, period=self.params.atr_period),
                'vol_ma': bt.indicators.SMA(d.volume, period=20),
                'rsi': bt.indicators.RSI(d.close, period=14)
            }
            self.orders[d] = None
            d.highest_price = 0.0 
        

    def log(self, txt, dt=None):
        if self.params.debug_verbose:
            dt = dt or self.data.datetime.date(0)
            print(f'{dt}: {txt}')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f"🟢 [成交] 买入 {order.data._name} 价格: {order.executed.price:.2f}")
                order.data.highest_price = order.executed.price
            elif order.issell():
                self.log(f"🔴 [成交] 卖出 {order.data._name} 价格: {order.executed.price:.2f} 盈亏: {order.executed.pnl:.2f}")
            self.orders[order.data] = None

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            status_text = "已取消/过期" if order.status == order.Canceled else "资金不足/被拒绝"
            # self.log(f"⚠️ [撤单] {order.data._name} 状态: {status_text}") # 嫌撤单刷屏可以注释掉这行
            self.orders[order.data] = None

    def next(self):
        # 1. 检查数据预热情况
        if self.first_run:
            print(f"\n📢 [系统] 策略在 {self.data.datetime.date(0)} 开始正式运行 (Next循环启动)")
            self.first_run = False

        # ----------------------------
        # 2. 大盘风控诊断
        # ----------------------------
        spy_price = self.spy.close[0]
        spy_ma = self.spy_ma200[0]

        if math.isnan(spy_ma):
            if self.data.datetime.date(0).day == 1:
                self.log(f"⏳ [预热中] SPY MA200 尚未生成，跳过交易...")
            return

        if spy_price < spy_ma:
            if self.data.datetime.date(0).day == 1:
                self.log(f"🛑 [风控] 熊市保护生效 (SPY {spy_price:.1f} < MA {spy_ma:.1f})")
            return 

        # ----------------------------
        # 3. 持仓管理
        # ----------------------------
        for d in self.broker.positions:
            if self.getposition(d).size > 0:
                if d.close[0] > d.highest_price:
                    d.highest_price = d.close[0]
                
                atr = self.inds[d]['atr'][0]
                stop_price = d.highest_price - (atr * self.params.stop_loss_atr)
                
                if d.close[0] < stop_price:
                    self.close(d)
                    self.log(f"🛡️ [止损触发] {d._name} 现价 {d.close[0]:.2f} < 止损线 {stop_price:.2f}")

        # ----------------------------
        # 4. 每日筛选漏斗诊断
        # ----------------------------
        reject_stats = {'price':0, 'trend':0, 'vol':0, 'rsi':0, 'atr':0, 'passed':0}
        candidates = []

        current_pos = len([d for d in self.broker.positions if self.getposition(d).size > 0])
        if current_pos >= self.params.max_pos:
            return

        for d in self.datas:
            # 【修复点 2】必须用 'is' 而不是 '=='
            if d is self.spy: continue
            
            if self.getposition(d).size > 0 or self.orders[d] is not None: continue
            
            # 检查个股指标是否预热完成
            if math.isnan(self.inds[d]['sma200'][0]): continue

            # --- 漏斗筛选 ---
            if d.close[0] < self.params.min_price: 
                reject_stats['price'] += 1
                continue
            
            if d.close[0] < self.inds[d]['sma200'][0]: 
                reject_stats['trend'] += 1
                continue

            if d.volume[0] < self.inds[d]['vol_ma'][0] * self.params.vol_multiplier: 
                reject_stats['vol'] += 1
                continue
                
            if self.inds[d]['rsi'][0] > self.params.rsi_threshold:
                reject_stats['rsi'] += 1
                continue

            prev_close = d.close[-1]
            change = d.close[0] - prev_close
            atr = self.inds[d]['atr'][0]
            
            if change > (atr * self.params.jump_threshold_atr):
                candidates.append((d, atr))
                reject_stats['passed'] += 1
            else:
                reject_stats['atr'] += 1

        # 仅当有信号时打印统计
        if len(candidates) > 0:
            self.log(f"🔎 [扫描统计] 趋势不符:{reject_stats['trend']} | 无量:{reject_stats['vol']} | 没涨够:{reject_stats['atr']} | ✅通过:{reject_stats['passed']}")

        # ----------------------------
        # 5. 执行交易
        # ----------------------------
        candidates.sort(key=lambda x: (x[0].close[0] - x[0].close[-1]) / x[1], reverse=True)
        
        slots = self.params.max_pos - current_pos
        for item in candidates[:slots]:
            target = item[0]
            atr = item[1]
            
            account_val = self.broker.get_value()
            risk_amt = account_val * self.params.risk_per_trade_pct
            stop_dist = atr * self.params.stop_loss_atr
            
            if stop_dist == 0: continue
            size = int(risk_amt / stop_dist)
            
            max_allowed_cash = account_val * 0.30
            if size * target.close[0] > max_allowed_cash:
                size = int(max_allowed_cash / target.close[0])

            if size > 0:
                trigger = target.close[0] * 1.001
                self.orders[target] = self.buy(
                    data=target, size=size, exectype=bt.Order.Stop, 
                    price=trigger, valid=datetime.timedelta(days=1)
                )
                self.log(f"⚡ [挂单] {target._name} 现价:{target.close[0]:.2f} 触发价:{trigger:.2f} (ATR:{atr:.2f})")

    def stop(self):
        print("\n=== 回测结束：当前持仓状态 ===")
        has_pos = False
        for d in self.datas:
            pos = self.getposition(d)
            if pos.size > 0:
                has_pos = True
                profit = (d.close[0] - pos.price) * pos.size
                print(f"📦 持仓: {d._name} | 成本: {pos.price:.2f} | 现价: {d.close[0]:.2f} | 浮盈: ${profit:.2f}")
        if not has_pos:
            print("空仓")