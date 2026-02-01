# strategies.py
import backtrader as bt
import pandas as pd
import datetime
import math
from screener import StockScreener
from portfolio import PortfolioManager

class ModularScreenerStrategy(bt.Strategy):
    params = (
        ('max_pos', 10),             # 最大持仓
        ('risk_per_trade_pct', 0.03),# 单笔风险 3%
        ('debug', True),             # 开启详细日志
        
        # 筛选参数
        ('min_price', 10.0),
        ('min_dollar_vol', 10000000), # 1000万成交额
    )

    def __init__(self):
        # 假设 SPY 是第一个数据
        self.spy = self.datas[0]
        # 计算大盘指标
        self.spy_ma200 = bt.indicators.SMA(self.spy.close, period=200)
        
        # 初始化投资组合管理器
        self.pm = PortfolioManager(
            initial_capital=self.broker.get_cash(),
            max_positions=self.params.max_pos,
            max_leverage=1.0
        )
        
        self.inds = {}
        self.orders = {} 

        print("🛠️ 初始化指标计算中...")

        # 预计算所有个股指标 (为 Screener 准备弹药)
        for d in self.datas:
            # 【关键修复】这里必须用 'is'，绝对不能用 '=='
            if d is self.spy: 
                continue
            
            self.inds[d] = {
                # 趋势指标
                'ma50': bt.indicators.SMA(d.close, period=50),
                'ma150': bt.indicators.SMA(d.close, period=150),
                'ma200': bt.indicators.SMA(d.close, period=200),
                
                # 波动与形态
                'atr': bt.indicators.ATR(d, period=14),
                'rsi': bt.indicators.RSI(d.close, period=14),
                'vol_ma': bt.indicators.SMA(d.volume, period=20),
                
                # 结构指标 (52周高低)
                'high52': bt.indicators.Highest(d.high, period=252),
                'low52': bt.indicators.Lowest(d.low, period=252),
            }
            self.orders[d] = None 
            d.highest_price = 0.0 # 用于移动止损

    def next(self):
        dt = self.data.datetime.date(0)

        # ---------------------------
        # 0. 大盘风控 (Gatekeeper)
        # ---------------------------
        # 如果 MA200 还没算出来(NaN)或者大盘跌破年线
        if math.isnan(self.spy_ma200[0]):
            return # 还在预热
            
        if self.spy.close[0] < self.spy_ma200[0]:
            if self.params.debug and dt.day == 1: # 每月提示一次
                print(f"🛑 {dt} [风控] 熊市保护生效 (SPY < MA200)")
            return

        # ---------------------------
        # 1. 准备全市场快照 (Snapshot)
        # ---------------------------
        snapshot_data = []
        
        for d in self.datas:
            if d is self.spy: continue
            
            # 确保个股指标也预热好了 (MA200最慢，只要它好了其他的都好了)
            if math.isnan(self.inds[d]['ma200'][0]): continue
            
            # 提取当日数据打包
            snapshot_data.append({
                'Ticker': d._name,
                'Close': d.close[0],
                'PrevClose': d.close[-1],
                'Volume': d.volume[0],
                
                # 技术指标
                'MA50': self.inds[d]['ma50'][0],
                'MA150': self.inds[d]['ma150'][0],
                'MA200': self.inds[d]['ma200'][0],
                'RSI': self.inds[d]['rsi'][0],
                'ATR': self.inds[d]['atr'][0],
                '52W_High': self.inds[d]['high52'][0],
                '52W_Low': self.inds[d]['low52'][0],
            })
        
        if not snapshot_data: return

        # 转换为 DataFrame
        df_today = pd.DataFrame(snapshot_data).set_index('Ticker')

        # ---------------------------
        # 2. 调用 Screener (核心选股)
        # ---------------------------
        screener = StockScreener(df_today)
        
        target_tickers = (
            screener
            # A. 流动性过滤
            .filter_liquidity(min_price=self.params.min_price, min_dollar_vol=self.params.min_dollar_vol)
            # B. 趋势过滤：用 trend_alignment(仅>MA200)，若改用 filter_trend_template() 会极严常为 0 只
            .filter_trend_alignment()
            # C. 动量过滤 (ATR启动)
            .filter_gap_up(threshold_atr=0.5)
            # D. 形态过滤
            .filter_rsi_setup(max_rsi=75)
            # E. 排序截断
            .rank_and_cut(top_n=5)
            .get_result()
        )
        
        # Debug: 选股结果与漏斗（无结果时每月打印一次漏斗便于排查）
        if self.params.debug and len(target_tickers) > 0:
            print(f"\n📅 {dt} 选股结果: {target_tickers}")
        elif self.params.debug and dt.day == 1 and len(screener.logs) > 0:
            print(f"📊 {dt} 筛选漏斗(本月样例): {' -> '.join(screener.logs)}")

        # ---------------------------
        # 3. 交易执行 (使用 PortfolioManager)
        # ---------------------------
        self.execute_trades(target_tickers)

    def execute_trades(self, target_tickers):
        """移动止损 + 使用 PortfolioManager 计算仓位并开新仓"""
        dt = self.data.datetime.date(0)
        account_val = self.broker.get_value()
        current_cash = self.broker.get_cash()
        
        # 1. 移动止损逻辑
        for d in self.broker.positions:
            if self.getposition(d).size > 0:
                if d.close[0] > d.highest_price:
                    d.highest_price = d.close[0]
                
                atr = self.inds[d]['atr'][0]
                stop_price = d.highest_price - (atr * 3.5)
                
                if d.close[0] < stop_price:
                    self.close(d)
                    print(f"🛡️ {dt} [止损] {d._name} 离场 (现价{d.close[0]:.2f} < 止损{stop_price:.2f})")

        # 2. 开新仓逻辑
        current_pos_count = len([d for d in self.broker.positions if self.getposition(d).size > 0])
        
        for ticker in target_tickers:
            if current_pos_count >= self.params.max_pos:
                break
            
            d = next((x for x in self.datas if x._name == ticker), None)
            if not d:
                continue
            
            if self.getposition(d).size == 0 and self.orders[d] is None:
                atr = self.inds[d]['atr'][0]
                size = self.pm.calculate_position_size(
                    account_value=account_val,
                    price=d.close[0],
                    atr=atr,
                    method='risk_parity',
                    risk_pct=self.params.risk_per_trade_pct,
                    stop_mult=3.5
                )
                
                est_cost = size * d.close[0]
                if not self.pm.check_cash_availability(current_cash, est_cost):
                    if self.params.debug:
                        print(f"⚠️ {dt} [资金不足] 无法买入 {ticker} (需 {est_cost:.0f}, 有 {current_cash:.0f})")
                    continue

                if size > 0:
                    trigger = d.close[0] * 1.001
                    self.orders[d] = self.buy(
                        data=d, size=size, exectype=bt.Order.Stop,
                        price=trigger, valid=datetime.timedelta(days=1)
                    )
                    current_cash -= est_cost
                    current_pos_count += 1
                    print(f"⚡ {dt} [挂单] {d._name} (ATR:{atr:.2f} 股数:{size})")

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                # 重置最高价用于移动止损
                order.data.highest_price = order.executed.price
                print(f"🟢 [成交] 买入 {order.data._name} @ {order.executed.price:.2f}")
            elif order.issell():
                print(f"🔴 [成交] 卖出 {order.data._name} @ {order.executed.price:.2f} 盈亏: {order.executed.pnl:.2f}")
            self.orders[order.data] = None

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.orders[order.data] = None