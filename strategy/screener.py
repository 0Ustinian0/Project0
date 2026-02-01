import pandas as pd


class StockScreener:
    def __init__(self, df_snapshot):
        self.df = df_snapshot.copy()
        self.initial_count = len(self.df)
        self.logs = []

    def _log(self, step_name):
        remaining = len(self.df)
        self.logs.append(f"{step_name}: 剩余 {remaining}")

    def filter_liquidity(self, min_price=10.0, min_volume=0, min_dollar_vol=None):
        self.df = self.df[
            (self.df['Close'] >= min_price) &
            (self.df['Volume'] > min_volume)
        ]
        if min_dollar_vol is not None:
            self.df = self.df[self.df['Close'] * self.df['Volume'] >= min_dollar_vol]
        self._log("流动性过滤")
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

    def rank_and_cut(self, sort_by='RelativeStrength', ascending=False, top_n=5):
        if sort_by == 'RelativeStrength':
            self.df['Score'] = (self.df['Close'] - self.df['PrevClose']) / self.df['ATR']
            sort_col = 'Score'
        else:
            sort_col = sort_by
        if sort_col in self.df.columns:
            self.df = self.df.sort_values(by=sort_col, ascending=ascending)
            self.df = self.df.head(top_n)
            self._log(f"排序截断(Top {top_n})")
        return self

    def get_result(self):
        return self.df.index.tolist()

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
