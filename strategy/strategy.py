import time
import math
import backtrader as bt
import pandas as pd
from strategy.screener import StockScreener
from strategy.order_manager import OrderManager
from strategy.signals import build_snapshot
from portfolio.manager import PortfolioManager
from utils.logger import Logger
from data.manager import load_fundamentals


class ModularScreenerStrategy(bt.Strategy):
    params = (
        ('max_pos', 10),
        ('risk_per_trade_pct', 0.03),
        ('debug', True),
        ('lookback_period', 20),
        ('entry_threshold', 0.02),
        ('exit_threshold', -0.01),
        ('min_price', 10.0),
        ('min_dollar_vol', 10000000),
        ('atr_period', 14),   # ATR 周期，优化时可对比 10/14/20 等
        ('rsi_period', 14),   # RSI 周期
        ('stop_atr_mult', 3.5),
        # 基本面（需 data_dir 下 fundamentals.csv；data_dir 由引擎注入）
        # 默认宽松：只剔极端差，夏普接近不加基本面；严格阈值会降夏普
        ('data_dir', None),
        ('fundamentals_enabled', False),
        ('max_pe', 200),
        ('min_roe', -0.25),
        ('max_pb', 100),
        ('min_revenue_growth', -0.30),
        ('max_debt_to_equity', 500),
    )

    def __init__(self):
        self.spy = self.datas[0]
        self.logger = Logger()
        self.pm = PortfolioManager(
            self.broker.get_cash(),
            max_positions=self.params.max_pos,
            max_leverage=1.0
        )
        self.om = OrderManager(self, debug=self.params.debug)
        self.fundamentals = None
        if self.params.fundamentals_enabled and getattr(self.params, 'data_dir', None):
            self.fundamentals = load_fundamentals(self.params.data_dir, logger=self.logger)
            if self.fundamentals is not None:
                self.logger.info("📋 基本面数据已加载，screener 将应用 PE/ROE/PB 等过滤")
        self.spy_ma200 = bt.indicators.SMA(self.spy.close, period=200)
        self.inds = {}
        self.logger.info("🛠️ 初始化指标计算中...")
        for d in self.datas:
            if d is self.spy:
                continue
            self.inds[d] = {
                'ma50': bt.indicators.SMA(d.close, period=50),
                'ma150': bt.indicators.SMA(d.close, period=150),
                'ma200': bt.indicators.SMA(d.close, period=200),
                'atr': bt.indicators.ATR(d, period=self.params.atr_period),
                'rsi': bt.indicators.RSI(d.close, period=self.params.rsi_period),
                'vol_ma': bt.indicators.SMA(d.volume, period=20),
                'high52': bt.indicators.Highest(d.high, period=252),
                'low52': bt.indicators.Lowest(d.low, period=252),
            }
            d.highest_price = 0.0

    def next(self):
        self.logger.show_progress(self.data.datetime.datetime(0))
        t_start = time.time()
        dt = self.data.datetime.date(0)
        if math.isnan(self.spy_ma200[0]):
            return
        if self.spy.close[0] < self.spy_ma200[0]:
            if self.params.debug and dt.day == 1:
                print(f"🛑 {dt} [风控] 熊市保护生效 (SPY < MA200)")
            return

        df_today = build_snapshot(self.datas, self.spy, self.inds)
        if df_today.empty:
            return
        if self.fundamentals is not None and not self.fundamentals.empty:
            df_today = df_today.join(self.fundamentals, how='left')

        screener = StockScreener(df_today)
        chain = (
            screener
            .filter_liquidity(min_price=self.params.min_price, min_dollar_vol=self.params.min_dollar_vol)
            .filter_trend_alignment()
            .filter_gap_up(threshold_atr=0.5)
            .filter_rsi_setup(max_rsi=75)
        )
        if self.fundamentals is not None and not self.fundamentals.empty:
            chain = (
                chain
                .filter_pe(max_pe=self.params.max_pe)
                .filter_pb(max_pb=self.params.max_pb)
                .filter_roe(min_roe=self.params.min_roe)
                .filter_revenue_growth(min_growth=self.params.min_revenue_growth)
                .filter_debt_to_equity(max_dte=self.params.max_debt_to_equity)
            )
        target_tickers = chain.rank_and_cut(top_n=5).get_result()
        if self.params.debug and len(target_tickers) > 0:
            print(f"\n📅 {dt} 选股结果: {target_tickers}")
        elif self.params.debug and dt.day == 1 and len(screener.logs) > 0:
            print(f"📊 {dt} 筛选漏斗(本月样例): {' -> '.join(screener.logs)}")

        self.execute_trades(target_tickers)

    def execute_trades(self, target_tickers):
        dt = self.data.datetime.date(0)
        account_val = self.broker.get_value()
        current_cash = self.broker.get_cash()
        for d in self.broker.positions:
            if self.getposition(d).size > 0:
                if d.close[0] > d.highest_price:
                    d.highest_price = d.close[0]
                atr = self.inds[d]['atr'][0]
                stop_price = d.highest_price - (atr * 3.5)
                if d.close[0] < stop_price:
                    if self.params.debug:
                        print(f"🛡️ {dt} [止损] {d._name} 离场 (现价{d.close[0]:.2f} < 止损{stop_price:.2f})")
                    self.om.sell_market(d)

        current_pos_count = len([d for d in self.broker.positions if self.getposition(d).size > 0])
        for ticker in target_tickers:
            if current_pos_count >= self.params.max_pos:
                break
            d = next((x for x in self.datas if x._name == ticker), None)
            if not d:
                continue
            if self.om.has_pending_order(d):
                continue
            if self.getposition(d).size > 0:
                continue
            atr = self.inds[d]['atr'][0]
            size = self.pm.calculate_position_size(
                account_value=account_val,
                price=d.close[0],
                atr=atr,
                method='risk_parity',
                risk_pct=self.params.risk_per_trade_pct,
                stop_mult=self.params.stop_atr_mult
            )
            est_cost = size * d.close[0]
            if not self.pm.check_cash_availability(current_cash, est_cost):
                if self.params.debug:
                    print(f"⚠️ {dt} [资金不足] 无法买入 {ticker} (需 {est_cost:.0f}, 有 {current_cash:.0f})")
                continue
            if size > 0:
                trigger = d.close[0] * 1.001
                self.om.buy_stop(data=d, size=size, price=trigger, valid_days=1)
                current_cash -= est_cost
                current_pos_count += 1
                if self.params.debug:
                    print(f"⚡ {dt} [挂单] {d._name} (ATR:{atr:.2f} 股数:{size})")

    def stop(self):
        print("")
        self.logger.info("策略运行结束。")

    def notify_order(self, order):
        self.om.process_status(order)
        if order.status == order.Completed and order.isbuy():
            order.data.highest_price = order.executed.price
