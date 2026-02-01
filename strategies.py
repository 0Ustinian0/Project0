# strategies.py (进阶版：趋势跟踪 + ATR风控)
import backtrader as bt
import datetime

class GapUpStrategy(bt.Strategy):
    params = (
        ('max_pos', 8),            # 最大持仓数（适当放宽，增加机会）
        ('risk_per_trade', 0.15),  # 每次仓位（略降，控制整体风险）
        ('min_price', 5.0),        # 价格过滤（允许更多标的）
        
        # --- 信号参数 ---
        ('big_candle_pct', 0.02),  # 昨日涨幅 > 2% 即视为启动，增加信号数量
        ('rsi_limit', 80),         # RSI 过滤：允许更高一点，减少过早过滤
        
        # --- 止损/止盈参数 ---
        ('atr_period', 14),       # ATR 周期
        ('atr_multiplier', 3.0),  # 3倍 ATR 止损 (宽止损，防洗盘)
    )

    def __init__(self):
        self.inds = {}
        self.orders = {}      
        
        for d in self.datas:
            self.inds[d] = {
                # 均线系统
                'sma200': bt.indicators.SMA(d.close, period=200),
                'sma50':  bt.indicators.SMA(d.close, period=50),
                
                # 波动率指标 ATR (用于止损)
                'atr': bt.indicators.ATR(d, period=self.params.atr_period),
                
                # 超买指标 RSI
                'rsi': bt.indicators.RSI(d.close, period=14)
            }
            self.orders[d] = None
            # 记录每只股票的最高价（用于移动止损）
            d.highest_price = 0.0 

    def log(self, txt, dt=None):
        dt = dt or self.data.datetime.date(0)
        print(f'{dt}: {txt}')

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'🟢 [买入成交] {order.data._name} @ ${order.executed.price:.2f}')
                # 买入后，初始化最高价为买入价
                order.data.highest_price = order.executed.price
            elif order.issell():
                pnl = order.executed.pnl
                self.log(f'🔴 [卖出成交] {order.data._name} @ ${order.executed.price:.2f} | 盈亏: ${pnl:.2f}')
            self.orders[order.data] = None

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.orders[order.data] = None

    def next(self):
        dt = self.data.datetime.date(0)
        # 每隔 30 天打印一次，证明我在跑（如果每天都打，屏幕会刷太快看不清）
        # len(self) 是当前回测运行的天数
        if len(self) % 30 == 0:
             print(f"❤️ [心跳检查] {dt} 正在扫描 {len(self.datas)} 只股票...")
        # 0. 获取大盘数据 (假设 SPY 是 datas[0])
        # 如果你没在 main.py 里把 SPY 放在第一个，这里会出错
        spy = self.datas[0] 
        if spy._name != 'SPY':
            # 防御性代码：如果没有加载 SPY，就打印警告并跳过风控（或者去寻找名为SPY的数据）
            # print("警告: Data0 不是 SPY，风控失效")
            pass
        else:
            # 计算 SPY 的 200 日均线 (需要预先在 __init__ 里定义 self.spy_ma200)
            spy_price = spy.close[0]
            spy_ma = self.inds[spy]['sma200'][0]
            
            # --- 【核心风控】 ---
            # 略微放宽风控条件：允许轻微跌破 MA200，只有明显跌破才视为熊市
            if spy_price < spy_ma * 0.97:
                if len(self) % 30 == 0:
                    print(f"🛑 [大盘风控] SPY({spy_price:.2f}) < MA200({spy_ma:.2f}) -> 熊市空仓休息")
                # 熊市禁止开新仓
                # 可选：是否清仓现有持仓？趋势策略通常选择不清仓，让个股止损自然触发
                return
        # ----------------------------
        # 1. 持仓管理 (ATR 移动止损)
        # ----------------------------
        for d in self.broker.positions:
            if self.getposition(d).size > 0:
                # 更新持仓期间的最高收盘价
                if d.close[0] > d.highest_price:
                    d.highest_price = d.close[0]
                
                # 计算动态止损线：最高价 - 3倍ATR
                # 随着股价上涨，止损线会跟着上移 (Trailing Stop)
                atr_value = self.inds[d]['atr'][0]
                stop_price = d.highest_price - (atr_value * self.params.atr_multiplier)
                
                # 如果收盘价跌破移动止损线 -> 离场
                if d.close[0] < stop_price:
                    self.close(d)
                    self.log(f"🛡️ [移动止损] {d._name} 回撤触发 (现价{d.close[0]:.2f} < 止损{stop_price:.2f})")

        # ----------------------------
        # 2. 每日筛选 (Screener)
        # ----------------------------
        current_pos_count = len([d for d in self.broker.positions if self.getposition(d).size > 0])
        if current_pos_count >= self.params.max_pos:
            return

        candidates = []

        for d in self.datas:
            if self.getposition(d).size > 0 or self.orders[d] is not None:
                continue
            if len(d) < 200: continue

            # --- 筛选条件 ---
            
            # 1. 价格与趋势 (要在200日线和50日线之上，多头排列)
            if d.close[0] < self.params.min_price: continue
            if d.close[0] < self.inds[d]['sma200'][0]: continue
            if d.close[0] < self.inds[d]['sma50'][0]: continue

            # 2. RSI 过滤 (拒绝超买)
            if self.inds[d]['rsi'][0] > self.params.rsi_limit: continue

            # 3. 信号触发: 昨日涨幅 > 3% (不必太大，太大容易力竭)
            prev_close = d.close[-1]
            if prev_close == 0: continue
            pct_change = (d.close[0] - prev_close) / prev_close
            
            if pct_change > self.params.big_candle_pct:
                candidates.append((d, pct_change))

        # ----------------------------
        # 3. 排序与执行
        # ----------------------------
        candidates.sort(key=lambda x: x[1], reverse=True)
        slots_available = self.params.max_pos - current_pos_count
        
        for item in candidates[:slots_available]:
            target_stock = item[0]
            pct_gain = item[1]
            
            cash = self.broker.get_value()
            target_cash = cash * self.params.risk_per_trade
            size = int(target_cash / target_stock.close[0])
            
            if size > 0:
                self.log(f"⚡ [信号] {target_stock._name} 启动(+{pct_gain:.1%}), RSI={self.inds[target_stock]['rsi'][0]:.1f}, 挂单...")
                
                # 依然使用 Stop 单追涨，稍微放宽一点触发价
                trigger_price = target_stock.close[0] * 1.001
                
                self.orders[target_stock] = self.buy(
                    data=target_stock,
                    size=size,
                    exectype=bt.Order.Stop,
                    price=trigger_price,
                    valid=datetime.timedelta(days=1) 
                )