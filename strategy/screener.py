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
