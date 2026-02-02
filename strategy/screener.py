import pandas as pd
import numpy as np

# 综合打分权重：长期趋势(ROC_126) 40% + 相对强弱(RSI) 30% + 短期爆发(ATR涨幅) 30%
DEFAULT_SCORE_WEIGHTS = {'roc126': 0.40, 'rsi': 0.30, 'atr_pct': 0.30}

# 双模信号类型
Signal_Breakout = 'Breakout'
Signal_Dip = 'Dip'


class StockScreener:
    def __init__(self, df_snapshot):
        self.df = df_snapshot.copy()
        self.initial_count = len(self.df)
        self.logs = []

    def _log(self, step_name):
        remaining = len(self.df)
        self.logs.append(f"{step_name}: 剩余 {remaining}")

    def filter_liquidity(self, min_price=10.0, min_volume=0, min_dollar_vol=None, min_avg_dollar_vol=None):
        """流动性：价格 + 当日量；可选 min_avg_dollar_vol 用 20 日均额（需 Volume_MA20）保证持续成交能力。"""
        self.df = self.df[
            (self.df['Close'] >= min_price) &
            (self.df['Volume'] > min_volume)
        ]
        if min_dollar_vol is not None:
            self.df = self.df[self.df['Close'] * self.df['Volume'] >= min_dollar_vol]
        if min_avg_dollar_vol is not None and 'Volume_MA20' in self.df.columns:
            avg_dollar = self.df['Close'] * self.df['Volume_MA20']
            self.df = self.df[avg_dollar >= min_avg_dollar_vol]
            self._log(f"持续流动性(20日均额≥{min_avg_dollar_vol/1e6:.0f}M)")
        self._log("流动性过滤")
        return self

    def filter_volume_vs_ma(self, vol_multiplier=None):
        """量比过滤：当日量 >= Volume_MA20 * vol_multiplier 才保留；vol_multiplier 为 None 时不筛。"""
        if vol_multiplier is None or vol_multiplier <= 0 or 'Volume_MA20' not in self.df.columns:
            return self
        self.df = self.df[self.df['Volume'] >= self.df['Volume_MA20'] * vol_multiplier]
        self._log(f"量比过滤(Volume≥MA20×{vol_multiplier})")
        return self

    def filter_trend_alignment(self):
        self.df = self.df.dropna(subset=['MA200'])
        self.df = self.df[self.df['Close'] > self.df['MA200']]
        self._log("趋势过滤(>MA200)")
        return self

    def filter_rsi_setup(self, min_rsi=0, max_rsi=100):
        self.df = self.df[
            (self.df['RSI'] >= min_rsi) &
            (self.df['RSI'] <= max_rsi)
        ]
        self._log(f"RSI过滤({min_rsi}-{max_rsi})")
        return self

    def calculate_composite_score(self, weights=None):
        """
        综合打分 0-100：40% 长期趋势(ROC_126) + 30% 相对强弱(RSI) + 30% 短期爆发(ATR_pct)。
        为末位淘汰提供量化依据；缺失列时跳过对应项并重算权重。
        """
        weights = weights or DEFAULT_SCORE_WEIGHTS
        req = {'ROC_126': 'roc126', 'RSI': 'rsi', 'ATR_pct': 'atr_pct'}
        available = {k: v for k, v in req.items() if k in self.df.columns}
        if not available:
            return self
        w_sum = sum(weights.get(v, 0) for v in available.values())
        if w_sum <= 0:
            return self
        score = pd.Series(0.0, index=self.df.index)
        for col, key in available.items():
            w = weights.get(key, 0) / w_sum
            s = self.df[col]
            if col == 'RSI':
                # RSI 已是 0-100
                s_norm = s.clip(0, 100) / 100.0
            else:
                # ROC_126 / ATR_pct：min-max 归一化到 0-1
                mn, mx = s.min(), s.max()
                if mx > mn:
                    s_norm = (s - mn) / (mx - mn)
                else:
                    s_norm = 0.5
            score = score + w * s_norm
        self.df['Score'] = (score * 100).clip(0, 100)
        self._log("综合打分")
        return self

    def filter_dip_setup(self):
        """低吸模式：价格 > 年线(MA200) 且 RSI < 35（牛回头）。"""
        if 'MA200' not in self.df.columns or 'RSI' not in self.df.columns:
            return self
        self.df = self.df[(self.df['Close'] > self.df['MA200']) & (self.df['RSI'] < 35)]
        self._log("低吸过滤(>MA200且RSI<35)")
        return self

    def filter_gap_up(self, threshold_atr=0.5):
        if 'PrevClose' not in self.df.columns:
            return self
        change = self.df['Close'] - self.df['PrevClose']
        min_change = self.df['ATR'] * threshold_atr
        self.df = self.df[change > min_change]
        self._log("动量启动过滤")
        return self

    def filter_volatility_control(self, max_atr_percent=0.05):
        volatility = self.df['ATR'] / self.df['Close']
        self.df = self.df[volatility <= max_atr_percent]
        self._log("波动率风控")
        return self

    def rank_and_cut(self, sort_by='Score', ascending=False, top_n=5):
        """sort_by: 'Score' 用综合打分，'RelativeStrength' 用 ATR 相对强度；无 Score 时 RelativeStrength 回退。"""
        if sort_by == 'RelativeStrength' and 'Score' not in self.df.columns:
            self.df['Score'] = (self.df['Close'] - self.df['PrevClose']) / self.df['ATR'].replace(0, np.nan)
            sort_col = 'Score'
        elif sort_by == 'Score' and 'Score' in self.df.columns:
            sort_col = 'Score'
        else:
            sort_col = sort_by if sort_by in self.df.columns else 'Score'
        if sort_col in self.df.columns:
            self.df = self.df.sort_values(by=sort_col, ascending=ascending)
            self.df = self.df.head(top_n)
            self._log(f"排序截断(Top {top_n}, by={sort_col})")
        return self

    def get_result(self):
        return self.df.index.tolist()

    def get_scores(self):
        """返回 ticker -> score 的 Series，供末位淘汰等使用；无 Score 列时返回空 Series。"""
        if 'Score' not in self.df.columns:
            return pd.Series(dtype=float)
        return self.df['Score'].copy()

    def filter_trend_template(self):
        required_cols = ['MA50', 'MA150', 'MA200', '52W_High', '52W_Low']
        if not all(col in self.df.columns for col in required_cols):
            return self
        self.df = self.df[
            (self.df['Close'] > self.df['MA50']) &
            (self.df['MA50'] > self.df['MA150']) &
            (self.df['MA150'] > self.df['MA200']) &
            (self.df['Close'] >= self.df['52W_Low'] * 1.25) &
            (self.df['Close'] >= self.df['52W_High'] * 0.75)
        ]
        self._log("超级趋势模板(Stage 2)")
        return self

    def filter_consolidation(self, max_bandwidth=0.10):
        if 'BB_Upper' not in self.df.columns:
            return self
        bandwidth = (self.df['BB_Upper'] - self.df['BB_Lower']) / self.df['MA20']
        self.df = self.df[bandwidth <= max_bandwidth]
        self._log(f"波动收缩(带宽<{max_bandwidth:.1%})")
        return self

    def filter_narrow_range(self, days=7):
        if 'Range' in self.df.columns and f'MinRange{days}' in self.df.columns:
            self.df = self.df[self.df['Range'] <= self.df[f'MinRange{days}']]
            self._log(f"NR{days}收缩形态")
        return self

    def filter_relative_strength(self, benchmark_pct_change):
        if 'PrevClose' not in self.df.columns:
            return self
        stock_pct_change = (self.df['Close'] - self.df['PrevClose']) / self.df['PrevClose']
        self.df = self.df[stock_pct_change > benchmark_pct_change]
        self._log("相对强弱(跑赢大盘)")
        return self

    def filter_inside_bar(self):
        cols = ['High', 'Low', 'PrevHigh', 'PrevLow']
        if not all(c in self.df.columns for c in cols):
            return self
        self.df = self.df[
            (self.df['High'] < self.df['PrevHigh']) &
            (self.df['Low'] > self.df['PrevLow'])
        ]
        self._log("Inside Bar形态")
        return self

    def _col(self, *names):
        """返回第一个存在的列名，用于兼容 PE/pe 等。"""
        for n in names:
            if n in self.df.columns:
                return n
        return None

    def filter_pe(self, max_pe=30, allow_negative=False):
        """市盈率过滤：有 PE 时需在 (0, max_pe]；无 PE 数据则保留。"""
        col = self._col('PE', 'pe')
        if col is None:
            return self
        mask_na = self.df[col].isna()
        if allow_negative:
            mask_ok = (self.df[col] <= max_pe) | (self.df[col] < 0)
        else:
            mask_ok = (self.df[col] > 0) & (self.df[col] <= max_pe)
        self.df = self.df[mask_na | mask_ok]
        self._log(f"PE过滤(≤{max_pe})")
        return self

    def filter_pb(self, max_pb=5, min_pb=0):
        """市净率过滤：有 PB 时需在 [min_pb, max_pb]；无数据则保留。"""
        col = self._col('PB', 'pb')
        if col is None:
            return self
        mask_na = self.df[col].isna()
        mask_ok = (self.df[col] >= min_pb) & (self.df[col] <= max_pb)
        self.df = self.df[mask_na | mask_ok]
        self._log(f"PB过滤({min_pb}~{max_pb})")
        return self

    def filter_roe(self, min_roe=0.10):
        """ROE 过滤：有 ROE 时需 ≥ min_roe（小数）；无数据则保留。"""
        col = self._col('ROE', 'roe')
        if col is None:
            return self
        mask_na = self.df[col].isna()
        mask_ok = self.df[col] >= min_roe
        self.df = self.df[mask_na | mask_ok]
        self._log(f"ROE过滤(≥{min_roe:.0%})")
        return self

    def filter_revenue_growth(self, min_growth=0.05):
        """营收增长过滤：有数据时需 ≥ min_growth；无数据则保留。"""
        col = self._col('RevenueGrowth', 'revenue_growth', 'revenuegrowth')
        if col is None:
            return self
        mask_na = self.df[col].isna()
        mask_ok = self.df[col] >= min_growth
        self.df = self.df[mask_na | mask_ok]
        self._log(f"营收增长过滤(≥{min_growth:.0%})")
        return self

    def filter_debt_to_equity(self, max_dte=2.0):
        """负债/权益过滤：有数据时需 ≤ max_dte；无数据则保留。"""
        col = self._col('DebtToEquity', 'debt_to_equity', 'debttoequity')
        if col is None:
            return self
        mask_na = self.df[col].isna()
        mask_ok = self.df[col] <= max_dte
        self.df = self.df[mask_na | mask_ok]
        self._log(f"负债权益比(≤{max_dte})")
        return self

    def filter_valuation(self, max_pe=50.0):
        """估值过滤：剔除 PE 过高或亏损股，保留 0 < PE ≤ max_pe；无 PE 数据则保留。"""
        col = self._col('PE', 'pe')
        if col is None:
            return self
        mask_na = self.df[col].isna()
        mask_ok = (self.df[col] > 0) & (self.df[col] <= max_pe)
        self.df = self.df[mask_na | mask_ok]
        self._log(f"估值过滤(0<PE≤{max_pe})")
        return self

    def filter_growth(self, min_eps_growth=None):
        """盈利增长过滤：EPS_Growth ≥ min_eps_growth（小数如 0.15=15%）；无数据则保留。min_eps_growth 为 None 时不筛。"""
        if min_eps_growth is None:
            return self
        col = self._col('EPS_Growth', 'eps_growth', 'epsgrowth')
        if col is None:
            return self
        mask_na = self.df[col].isna()
        mask_ok = self.df[col] >= min_eps_growth
        self.df = self.df[mask_na | mask_ok]
        self._log(f"成长过滤(EPS增长≥{min_eps_growth:.0%})")
        return self

    def filter_sustained_liquidity(self, min_avg_dollar_vol=None):
        """持续流动性：20 日均成交额 ≥ min_avg_dollar_vol（需 Volume_MA20）。"""
        if min_avg_dollar_vol is None or 'Volume_MA20' not in self.df.columns:
            return self
        avg_dollar = self.df['Close'] * self.df['Volume_MA20']
        self.df = self.df[avg_dollar >= min_avg_dollar_vol]
        self._log(f"持续流动性(20日均额≥{min_avg_dollar_vol/1e6:.0f}M)")
        return self

    def filter_sector(self, sector_name=None):
        """板块过滤：只看指定 Sector；sector_name 为 None 或空时不筛。"""
        if not sector_name or str(sector_name).strip() == '':
            return self
        col = self._col('Sector', 'sector')
        if col is None:
            return self
        self.df = self.df[self.df[col].astype(str).str.strip().str.lower() == str(sector_name).strip().lower()]
        self._log(f"板块过滤({sector_name})")
        return self

    def calculate_weights(self, method='equal'):
        count = len(self.df)
        if count == 0:
            return self
        if method == 'equal':
            self.df['Weight'] = 1.0 / count
        elif method == 'risk_parity':
            inv_vol = 1.0 / self.df['ATR']
            total_inv_vol = inv_vol.sum()
            self.df['Weight'] = inv_vol / total_inv_vol
        return self
