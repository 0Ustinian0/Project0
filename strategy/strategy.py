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
        # 动态 ATR 倍数（按波动率/板块调整 stop_atr_mult）
        ('dynamic_stop_enabled', False),
        # ATR% 分组阈值：atr_pct <= low 视为低波动；atr_pct >= high 视为高波动；中间用 stop_atr_mult
        ('atr_pct_low', 0.02),
        ('atr_pct_high', 0.05),
        ('stop_mult_low_vol', 2.5),
        ('stop_mult_high_vol', 3.5),
        # 板块系数：mult = mult * factor（例如 Technology: 1.15 更宽松；Utilities: 0.9 更紧）
        ('sector_stop_mult_factors', {}),
        # 末位淘汰安全阀
        ('replace_protect_enabled', True),
        ('replace_good_score_floor', 60.0),    # 得分≥该值视为“及格”，不强制轮动
        ('replace_good_above_ma20', True),     # 价格在 MA20 之上视为“仍强”，不强制轮动
        ('replace_weak_rsi_floor', 50.0),      # 仅当 RSI < 该值才视为“走弱”允许轮动
        ('replace_winner_protect_pct', 0.10),  # 浮盈≥10% 视为“大赢家”，不轮动
        ('replace_stronger_ratio', 1.2),       # 新股得分需 > 旧股得分 * ratio 才替换
        # 量比过滤：当日量 >= Volume_MA20 * vol_multiplier 才入池；None 表示不启用
        ('vol_multiplier', None),
        # 时间止损：买入后 N 天未涨则市价清仓，释放资金；time_stop_enabled=False 时关闭
        ('time_stop_enabled', True),
        ('time_stop_days', 5),
        # RSI 超买止盈：RSI > 阈值时分批减仓（按比例卖出）
        ('rsi_overbought', 80),
        ('rsi_reduce_pct', 0.5),
        # 移动止盈：价格创新高后，止盈线 = 最高价 * (1 - take_profit_pct)，回撤超过此比例时止盈
        ('take_profit_pct', 0.05),  # 5% 回撤止盈
        ('take_profit_enabled', True),
        # 分批止盈：浮盈达到不同 ATR 倍数时分别止盈一部分（如 1ATR 止盈 25%，2ATR 止盈 25%，3ATR 止盈 50%）
        ('take_profit_atr_levels', [1.0, 2.0, 3.0]),  # ATR 倍数列表
        ('take_profit_atr_pcts', [0.25, 0.25, 0.5]),  # 对应的止盈比例
        ('take_profit_atr_enabled', True),
        # 基本面（需 data_dir 下 fundamentals.csv；data_dir 由引擎注入）
        # 默认宽松：只剔极端差，夏普接近不加基本面；严格阈值会降夏普
        ('data_dir', None),
        ('fundamentals_enabled', False),
        ('max_pe', 200),
        ('min_roe', -0.25),
        ('max_pb', 100),
        ('min_revenue_growth', -0.30),
        ('max_debt_to_equity', 500),
        ('min_eps_growth', None),
        ('sector', None),
        ('top_n', 5),
        # 基本面开启时：提高流动性门槛，保证剩余标的成交充足；候选为 0 时是否用宽松基本面重试
        ('min_avg_dollar_vol', None),
        ('min_candidates_after_fundamentals', 0),
    )

    def __init__(self):
        self.spy = self.datas[0]
        self.logger = Logger()
        self._executed_orders = []  # 用于可视化：每笔成交 (date, ticker, side, price, size)
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
                self.logger.info(f"📚 基本面数据已加载 {len(self.fundamentals)} 条，screener 将应用 PE/EPS 增长/板块等过滤")
        self.spy_ma200 = bt.indicators.SMA(self.spy.close, period=200)
        self.inds = {}
        self.logger.info("🛠️ 初始化指标计算中...")
        for d in self.datas:
            if d is self.spy:
                continue
            self.inds[d] = {
                'ma20': bt.indicators.SMA(d.close, period=20),
                'ma50': bt.indicators.SMA(d.close, period=50),
                'ma150': bt.indicators.SMA(d.close, period=150),
                'ma200': bt.indicators.SMA(d.close, period=200),
                'atr': bt.indicators.ATR(d, period=self.params.atr_period),
                'rsi': bt.indicators.RSI(d.close, period=self.params.rsi_period),
                'vol_ma': bt.indicators.SMA(d.volume, period=20),
                'high52': bt.indicators.Highest(d.high, period=252),
                'low52': bt.indicators.Lowest(d.low, period=252),
                'roc126': bt.indicators.ROC(d.close, period=126),  # 长期趋势，综合打分用
            }
            d.highest_price = 0.0
            d.buy_date = None
            d.entry_price = None
            d.target_shares = None  # 金字塔目标股数，首仓 50% 后加仓用
            d.take_profit_levels_hit = []  # 已触发的分批止盈级别（ATR倍数），避免重复止盈

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

        min_avg = getattr(self.params, 'min_avg_dollar_vol', None)
        vol_mult = getattr(self.params, 'vol_multiplier', None)
        top_n = getattr(self.params, 'top_n', 5)

        # 全市场综合打分，供末位淘汰时查任意标的得分
        screener_all = StockScreener(df_today.copy())
        screener_all.calculate_composite_score()
        all_scores = screener_all.get_scores()

        def _fundamentals_chain(s):
            if self.fundamentals is not None and not self.fundamentals.empty:
                s = s.filter_valuation(max_pe=self.params.max_pe)
                if getattr(self.params, 'min_eps_growth', None) is not None:
                    s = s.filter_growth(min_eps_growth=self.params.min_eps_growth)
                if getattr(self.params, 'sector', None):
                    s = s.filter_sector(sector_name=self.params.sector)
                s = (
                    s.filter_pb(max_pb=self.params.max_pb)
                    .filter_roe(min_roe=self.params.min_roe)
                    .filter_revenue_growth(min_growth=self.params.min_revenue_growth)
                    .filter_debt_to_equity(max_dte=self.params.max_debt_to_equity)
                )
            return s

        # 追涨：动量启动 + RSI 0–75
        screener_b = StockScreener(df_today.copy())
        chain_b = (
            screener_b
            .filter_liquidity(
                min_price=self.params.min_price,
                min_dollar_vol=self.params.min_dollar_vol,
                min_avg_dollar_vol=min_avg,
            )
            .filter_volume_vs_ma(vol_multiplier=vol_mult)
            .filter_trend_alignment()
            .filter_gap_up(threshold_atr=0.5)
            .filter_rsi_setup(max_rsi=75)
        )
        chain_b = _fundamentals_chain(chain_b)
        chain_b.calculate_composite_score().rank_and_cut(sort_by='Score', ascending=False, top_n=top_n)
        breakout_tickers = chain_b.get_result()
        breakout_scores = chain_b.get_scores()

        # 低吸：价格 > 年线 且 RSI < 35
        screener_d = StockScreener(df_today.copy())
        chain_d = (
            screener_d
            .filter_liquidity(
                min_price=self.params.min_price,
                min_dollar_vol=self.params.min_dollar_vol,
                min_avg_dollar_vol=min_avg,
            )
            .filter_volume_vs_ma(vol_multiplier=vol_mult)
            .filter_trend_alignment()
            .filter_dip_setup()
        )
        chain_d = _fundamentals_chain(chain_d)
        chain_d.calculate_composite_score().rank_and_cut(sort_by='Score', ascending=False, top_n=top_n)
        dip_tickers = chain_d.get_result()
        dip_scores = chain_d.get_scores()

        # 合并两类信号（同一标的取较高分），按综合得分排序取前 top_n
        candidate_scores = pd.concat([breakout_scores, dip_scores])
        candidate_scores = candidate_scores.groupby(candidate_scores.index).max().sort_values(ascending=False).head(top_n * 2)
        target_tickers = candidate_scores.index.tolist()[:top_n]
        if self.params.debug and (breakout_tickers or dip_tickers):
            print(f"\n📅 {dt} 选股: 追涨 {breakout_tickers} | 低吸 {dip_tickers} → 合并 {target_tickers}")

        self.execute_trades(target_tickers, all_scores=all_scores, df_today=df_today)

    def _position_sector_counts(self, df_today=None):
        """当前持仓按板块计数；df_today 需含 Sector 列（来自 fundamentals join）。"""
        sector_col = 'Sector'
        if df_today is None or sector_col not in df_today.columns:
            return {}
        from collections import Counter
        counts = Counter()
        for d in self.datas:
            if d is self.spy:
                continue
            pos = self.getposition(d)
            if pos.size <= 0:
                continue
            ticker = d._name
            if ticker not in df_today.index:
                continue
            sec = df_today.loc[ticker, sector_col]
            if pd.isna(sec):
                sec = '_Unknown'
            counts[str(sec).strip()] += 1
        return dict(counts)

    def _effective_stop_mult(self, data, df_today=None):
        """
        计算单只股票的动态 ATR 倍数：
        1) 按 ATR% 分组决定基础倍数
        2) 再按板块做系数调整（可选）
        """
        base = float(self.params.stop_atr_mult)
        if not getattr(self.params, 'dynamic_stop_enabled', False):
            return base
        try:
            atr = float(self.inds[data]['atr'][0])
            price = float(data.close[0])
        except Exception:
            return base
        if price <= 0 or atr <= 0:
            return base
        atr_pct = atr / price
        low = float(getattr(self.params, 'atr_pct_low', 0.02))
        high = float(getattr(self.params, 'atr_pct_high', 0.05))
        if atr_pct <= low:
            mult = float(getattr(self.params, 'stop_mult_low_vol', base))
        elif atr_pct >= high:
            mult = float(getattr(self.params, 'stop_mult_high_vol', base))
        else:
            mult = base

        # 板块加成/收紧
        factors = getattr(self.params, 'sector_stop_mult_factors', None) or {}
        if df_today is not None and (not df_today.empty) and 'Sector' in df_today.columns and data._name in df_today.index:
            sec = df_today.loc[data._name, 'Sector']
            if not pd.isna(sec):
                sec_key = str(sec).strip()
                f = factors.get(sec_key)
                if f is None:
                    # 兼容大小写/空格差异
                    for k, v in factors.items():
                        if str(k).strip().lower() == sec_key.lower():
                            f = v
                            break
                if f is not None:
                    try:
                        mult = mult * float(f)
                    except Exception:
                        pass
        # 合理范围保护
        return max(1.0, float(mult))

    def execute_trades(self, target_tickers, all_scores=None, df_today=None):
        dt = self.data.datetime.date(0)
        account_val = self.broker.get_value()
        current_cash = self.broker.get_cash()
        all_scores = all_scores if all_scores is not None else pd.Series(dtype=float)
        df_today = df_today if df_today is not None else pd.DataFrame()

        for d in self.broker.positions:
            pos = self.getposition(d)
            if pos.size <= 0:
                continue
            if d.close[0] > d.highest_price:
                d.highest_price = d.close[0]
            atr = self.inds[d]['atr'][0]
            rsi = self.inds[d]['rsi'][0]
            entry_price = getattr(d, 'entry_price', None) or pos.price
            target_shares = getattr(d, 'target_shares', None) or pos.size

            # 1) ATR 跟踪止损
            stop_mult = self._effective_stop_mult(d, df_today=df_today)
            stop_price = d.highest_price - (atr * stop_mult)
            if d.close[0] < stop_price:
                if self.params.debug:
                    print(f"🛡️ {dt} [止损] {d._name} 离场 (现价{d.close[0]:.2f} < 止损{stop_price:.2f}, mult={stop_mult:.2f})")
                self.om.sell_market(d)
                continue
            # 2) 时间止损：买入后 N 天未涨则清仓（time_stop_enabled=False 时跳过）
            if self.params.time_stop_enabled and getattr(d, 'buy_date', None) is not None and getattr(d, 'entry_price', None) is not None:
                days_held = (dt - d.buy_date).days
                if days_held >= self.params.time_stop_days and d.close[0] <= d.entry_price:
                    if self.params.debug:
                        print(f"⏱️ {dt} [时间止损] {d._name} 持有{days_held}天未涨 (现价{d.close[0]:.2f} ≤ 成本{d.entry_price:.2f})")
                    self.om.sell_market(d)
                    continue
            # 3) 移动止盈：价格创新高后，回撤超过 take_profit_pct 时止盈
            if self.params.take_profit_enabled and d.highest_price > 0 and atr and atr > 0:
                take_profit_price = d.highest_price * (1 - self.params.take_profit_pct)
                if d.close[0] < take_profit_price:
                    if self.params.debug:
                        print(f"💰 {dt} [移动止盈] {d._name} 回撤{self.params.take_profit_pct:.1%} (最高{d.highest_price:.2f} → 现价{d.close[0]:.2f})")
                    self.om.sell_market(d)
                    continue

            # 4) 分批止盈：浮盈达到不同 ATR 倍数时分别止盈一部分
            if self.params.take_profit_atr_enabled and atr and atr > 0 and entry_price:
                unrealized = d.close[0] - entry_price
                unrealized_atr = unrealized / atr if atr > 0 else 0
                levels_hit = getattr(d, 'take_profit_levels_hit', [])
                levels = self.params.take_profit_atr_levels
                pcts = self.params.take_profit_atr_pcts
                for i, (level, pct) in enumerate(zip(levels, pcts)):
                    if unrealized_atr >= level and i not in levels_hit and pos.size >= 2:
                        reduce_size = max(1, int(pos.size * pct))
                        if self.params.debug:
                            print(f"📊 {dt} [分批止盈] {d._name} 浮盈{unrealized_atr:.1f}ATR 止盈{pct:.0%} ({reduce_size}/{pos.size})")
                        self.om.sell_market(d, size=reduce_size)
                        levels_hit.append(i)
                        d.take_profit_levels_hit = levels_hit
                        break  # 一次只触发一个级别

            # 5) RSI 超买止盈：分批止盈 50%
            if not math.isnan(rsi) and rsi > self.params.rsi_overbought and pos.size >= 2:
                reduce_size = max(1, int(pos.size * self.params.rsi_reduce_pct))
                if self.params.debug:
                    print(f"📉 {dt} [RSI止盈] {d._name} RSI={rsi:.1f}>80 减仓 {reduce_size}/{pos.size}")
                self.om.sell_market(d, size=reduce_size)
                continue
            # 6) 金字塔加仓：浮盈 > 1.5 ATR 且 仓位 < 目标，加仓剩余 30%–50%
            if target_shares is not None and pos.size < target_shares and atr and atr > 0:
                unrealized = d.close[0] - entry_price
                if unrealized > 1.5 * atr:
                    add_max = target_shares - pos.size
                    add_size = max(1, int(add_max * 0.4))  # 加仓剩余 40%
                    if add_size > 0 and current_cash >= add_size * d.close[0]:
                        trigger = d.close[0] * 1.001
                        self.om.buy_stop(data=d, size=min(add_size, add_max), price=trigger, valid_days=1)
                        current_cash -= add_size * d.close[0]
                        if self.params.debug:
                            print(f"📈 {dt} [金字塔] {d._name} 浮盈>{1.5*atr:.2f} 加仓 {add_size}")
                continue

        current_pos_count = len([d for d in self.broker.positions if self.getposition(d).size > 0])
        sector_counts = self._position_sector_counts(df_today)

        def sector_ok(ticker):
            if df_today.empty or ticker not in df_today.index or 'Sector' not in df_today.columns:
                return True
            sec = df_today.loc[ticker, 'Sector']
            if pd.isna(sec):
                return True
            return sector_counts.get(str(sec).strip(), 0) < 2

        # 末位淘汰：满仓时若最强候选得分 > 最弱持仓得分 * 1.2，则卖出最弱、买入最强
        if current_pos_count >= self.params.max_pos and target_tickers and not all_scores.empty:
            held = [x for x in self.datas if x is not self.spy and self.getposition(x).size > 0]
            held_scores = [(d, all_scores.get(d._name, 0)) for d in held]
            if held_scores:
                weakest_d, weakest_score = min(held_scores, key=lambda t: t[1])
                best_ticker = target_tickers[0]
                best_score = all_scores.get(best_ticker, 0)
                ratio = float(getattr(self.params, 'replace_stronger_ratio', 1.2))

                # 安全阀：保护“及格持仓”和“高浮盈持仓”
                if getattr(self.params, 'replace_protect_enabled', True):
                    # 1) 及格线：得分≥floor 或 价格在 MA20 上方则不轮动
                    good_floor = float(getattr(self.params, 'replace_good_score_floor', 60.0))
                    good_enough = weakest_score >= good_floor
                    close_now = None
                    ma20 = None
                    rsi_now = None
                    if not df_today.empty and weakest_d._name in df_today.index:
                        close_now = df_today.loc[weakest_d._name, 'Close'] if 'Close' in df_today.columns else None
                        ma20 = df_today.loc[weakest_d._name, 'MA20'] if 'MA20' in df_today.columns else None
                        rsi_now = df_today.loc[weakest_d._name, 'RSI'] if 'RSI' in df_today.columns else None
                    if getattr(self.params, 'replace_good_above_ma20', True) and close_now is not None and ma20 is not None:
                        try:
                            if not pd.isna(close_now) and not pd.isna(ma20) and float(close_now) > float(ma20):
                                good_enough = True
                        except Exception:
                            pass

                    # 2) 大赢家保护：浮盈≥winner_pct 不轮动
                    winner_pct = float(getattr(self.params, 'replace_winner_protect_pct', 0.10))
                    profit_pct = 0.0
                    try:
                        entry = getattr(weakest_d, 'entry_price', None) or self.getposition(weakest_d).price
                        if entry and entry > 0:
                            profit_pct = (float(weakest_d.close[0]) - float(entry)) / float(entry)
                    except Exception:
                        profit_pct = 0.0
                    winner_protect = profit_pct >= winner_pct

                    # 3) “确实走弱”条件：跌破 MA20 或 RSI < floor_rsi 才允许轮动
                    weak_rsi_floor = float(getattr(self.params, 'replace_weak_rsi_floor', 50.0))
                    is_weak = False
                    if close_now is not None and ma20 is not None:
                        try:
                            if not pd.isna(close_now) and not pd.isna(ma20) and float(close_now) < float(ma20):
                                is_weak = True
                        except Exception:
                            pass
                    if rsi_now is not None:
                        try:
                            if not pd.isna(rsi_now) and float(rsi_now) < weak_rsi_floor:
                                is_weak = True
                        except Exception:
                            pass

                    if good_enough or winner_protect or (not is_weak):
                        # 满足任一保护条件则不替换
                        if self.params.debug and (good_enough or winner_protect):
                            why = []
                            if good_enough:
                                why.append("good_enough")
                            if winner_protect:
                                why.append(f"winner({profit_pct:.1%})")
                            if not is_weak:
                                why.append("not_weak")
                            print(f"🧯 {dt} [轮动保护] 保留 {weakest_d._name}({weakest_score:.1f}) 原因: {', '.join(why)}")
                        best_score = -1  # 强制不触发替换

                if best_score > weakest_score * ratio and sector_ok(best_ticker):
                    if self.params.debug:
                        print(f"🔄 {dt} [末位淘汰] 卖出最弱 {weakest_d._name}({weakest_score:.1f}) 买入 {best_ticker}({best_score:.1f}) ratio={ratio:.2f}")
                    self.om.sell_market(weakest_d)
                    current_pos_count -= 1
                    current_cash += self.getposition(weakest_d).size * weakest_d.close[0]
                    target_tickers = [t for t in target_tickers if t != best_ticker]
                    d_new = next((x for x in self.datas if x._name == best_ticker), None)
                    if d_new and not self.om.has_pending_order(d_new) and self.getposition(d_new).size == 0:
                        atr = self.inds[d_new]['atr'][0]
                        size_full = self.pm.calculate_position_size(
                            account_value=account_val,
                            price=d_new.close[0],
                            atr=atr,
                            method='risk_parity',
                            risk_pct=self.params.risk_per_trade_pct,
                            stop_mult=self._effective_stop_mult(d_new, df_today=df_today),
                        )
                        entry_size = self.pm.get_first_entry_size(size_full)
                        est = entry_size * d_new.close[0]
                        if self.pm.check_cash_availability(current_cash, est) and entry_size > 0:
                            d_new.target_shares = size_full
                            trigger = d_new.close[0] * 1.001
                            self.om.buy_stop(data=d_new, size=entry_size, price=trigger, valid_days=1)
                            current_cash -= est
                            current_pos_count += 1

        for ticker in target_tickers:
            if current_pos_count >= self.params.max_pos:
                break
            if not sector_ok(ticker):
                if self.params.debug:
                    print(f"🚫 {dt} [板块熔断] {ticker} 所属板块已满 2 只，跳过")
                continue
            d = next((x for x in self.datas if x._name == ticker), None)
            if not d:
                continue
            if self.om.has_pending_order(d):
                continue
            if self.getposition(d).size > 0:
                continue
            atr = self.inds[d]['atr'][0]
            size_full = self.pm.calculate_position_size(
                account_value=account_val,
                price=d.close[0],
                atr=atr,
                method='risk_parity',
                risk_pct=self.params.risk_per_trade_pct,
                stop_mult=self._effective_stop_mult(d, df_today=df_today),
            )
            entry_size = self.pm.get_first_entry_size(size_full)
            est_cost = entry_size * d.close[0]
            if not self.pm.check_cash_availability(current_cash, est_cost):
                if self.params.debug:
                    print(f"⚠️ {dt} [资金不足] 无法买入 {ticker} (需 {est_cost:.0f}, 有 {current_cash:.0f})")
                continue
            if entry_size > 0:
                d.target_shares = size_full
                trigger = d.close[0] * 1.001
                self.om.buy_stop(data=d, size=entry_size, price=trigger, valid_days=1)
                current_cash -= est_cost
                current_pos_count += 1
                if self.params.debug:
                    print(f"⚡ {dt} [挂单] {d._name} 首仓50% (ATR:{atr:.2f} 股数:{entry_size}/{size_full})")

    def stop(self):
        print("")
        self.logger.info("策略运行结束。")

    def notify_order(self, order):
        self.om.process_status(order)
        if order.status == order.Completed:
            if order.isbuy():
                # 更新最高价（如果新成交价更高）
                if order.executed.price > getattr(order.data, 'highest_price', 0):
                    order.data.highest_price = order.executed.price
                # 首次买入时设置成本价和买入日期，重置止盈状态
                pos = self.getposition(order.data)
                if pos.size == order.executed.size:  # 首次买入（持仓等于本次买入量）
                    order.data.entry_price = order.executed.price
                    order.data.buy_date = self.data.datetime.date(0)
                    order.data.take_profit_levels_hit = []  # 首次买入时重置分批止盈状态
                elif not hasattr(order.data, 'entry_price') or order.data.entry_price is None:
                    # 如果没有成本价，设置（加仓情况）
                    order.data.entry_price = order.executed.price
            # 记录成交供买卖点图使用（排除 SPY）
            if order.data._name != 'SPY':
                dt = getattr(order.executed, 'dt', None)
                if dt is not None and hasattr(dt, 'date'):
                    dt = dt.date()
                else:
                    dt = self.data.datetime.date(0)
                self._executed_orders.append({
                    'date': dt,
                    'ticker': order.data._name,
                    'side': 'buy' if order.isbuy() else 'sell',
                    'price': order.executed.price,
                    'size': order.executed.size,
                })
