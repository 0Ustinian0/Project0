import pandas as pd

class StockScreener:
    def __init__(self, df_snapshot):
        """
        初始化筛选器
        :param df_snapshot: 包含当日所有股票数据的 DataFrame
                            Index: Ticker (股票代码)
                            Columns: Close, Volume, MA200, RSI, ATR, Sector, etc.
        """
        # 复制数据以防污染源数据
        self.df = df_snapshot.copy()
        self.initial_count = len(self.df)
        self.logs = []

    def _log(self, step_name):
        """记录每一步筛选后的剩余数量"""
        remaining = len(self.df)
        self.logs.append(f"{step_name}: 剩余 {remaining}")

    # ==========================================
    # A. 基础流动性筛选
    # ==========================================
    def filter_liquidity(self, min_price=10.0, min_volume=0, min_dollar_vol=None):
        """过滤低价股、无量股和成交额不足的股票"""
        self.df = self.df[
            (self.df['Close'] >= min_price) &
            (self.df['Volume'] > min_volume)
        ]
        if min_dollar_vol is not None:
            self.df = self.df[self.df['Close'] * self.df['Volume'] >= min_dollar_vol]
        self._log("流动性过滤")
        return self

    # ==========================================
    # B. 趋势与技术面筛选
    # ==========================================
    def filter_trend_alignment(self):
        """核心趋势过滤：价格必须在年线之上"""
        # 确保 MA200 不是 NaN (排除预热期数据不足的股票)
        self.df = self.df.dropna(subset=['MA200'])
        self.df = self.df[self.df['Close'] > self.df['MA200']]
        self._log("趋势过滤(>MA200)")
        return self

    def filter_rsi_setup(self, min_rsi=0, max_rsi=100):
        """RSI 区间过滤"""
        self.df = self.df[
            (self.df['RSI'] >= min_rsi) & 
            (self.df['RSI'] <= max_rsi)
        ]
        self._log(f"RSI过滤({min_rsi}-{max_rsi})")
        return self

    def filter_gap_up(self, threshold_atr=0.5):
        """
        Gap Up / 启动形态过滤
        逻辑：(今日收盘 - 昨日收盘) > 阈值 * ATR
        """
        # 注意：这里需要传入 'PrevClose'，在策略层准备数据时要算好
        if 'PrevClose' not in self.df.columns:
            return self
            
        change = self.df['Close'] - self.df['PrevClose']
        min_change = self.df['ATR'] * threshold_atr
        
        self.df = self.df[change > min_change]
        self._log("动量启动过滤")
        return self

    # ==========================================
    # C. 风险与波动率过滤
    # ==========================================
    def filter_volatility_control(self, max_atr_percent=0.05):
        """
        剔除波动率过大的妖股
        逻辑：ATR / Price <= 5% (举例)
        """
        volatility = self.df['ATR'] / self.df['Close']
        self.df = self.df[volatility <= max_atr_percent]
        self._log("波动率风控")
        return self

    # ==========================================
    # D. 排序与截断
    # ==========================================
    def rank_and_cut(self, sort_by='RelativeStrength', ascending=False, top_n=5):
        """
        最终排序，选出前 N 名
        RelativeStrength = (Price - PrevPrice) / ATR
        """
        if sort_by == 'RelativeStrength':
            # 动态计算相对强度因子
            self.df['Score'] = (self.df['Close'] - self.df['PrevClose']) / self.df['ATR']
            sort_col = 'Score'
        else:
            sort_col = sort_by

        if sort_col in self.df.columns:
            self.df = self.df.sort_values(by=sort_col, ascending=ascending)
            self.df = self.df.head(top_n)
            self._log(f"排序截断(Top {top_n})")
        
        return self

    # ==========================================
    # E. 获取结果
    # ==========================================
    def get_result(self):
        """返回最终的股票代码列表"""
        # print(f"🔍 筛选漏斗: {' -> '.join(self.logs)}")
        return self.df.index.tolist()

    # ==========================================
    # F. 超级趋势模板
    # ==========================================
    def filter_trend_template(self):
        """
        Mark Minervini 'Stage 2' 趋势模板：
        1. 价格 > MA50 > MA150 > MA200
        2. 价格比 52周低点高至少 25%
        3. 价格在 52周高点的 25% 范围内 (接近新高)
        """
        required_cols = ['MA50', 'MA150', 'MA200', '52W_High', '52W_Low']
        # 检查列是否存在，不存在则跳过 (容错)
        if not all(col in self.df.columns for col in required_cols):
            return self

        self.df = self.df[
            (self.df['Close'] > self.df['MA50']) &
            (self.df['MA50'] > self.df['MA150']) &
            (self.df['MA150'] > self.df['MA200']) &
            (self.df['Close'] >= self.df['52W_Low'] * 1.25) & # 底部上涨超25%
            (self.df['Close'] >= self.df['52W_High'] * 0.75)  # 处在历史高位附近
        ]
        self._log("超级趋势模板(Stage 2)")
        return self

    # ==========================================
    # G. 横盘整理与变盘信号
    # ==========================================
    def filter_consolidation(self, max_bandwidth=0.10):
        """
        寻找横盘整理的股票 (Bollinger Bandwidth Squeeze)
        Bandwidth = (Upper - Lower) / Middle
        :param max_bandwidth: 带宽阈值，越小越窄
        """
        if 'BB_Upper' not in self.df.columns: return self
        
        bandwidth = (self.df['BB_Upper'] - self.df['BB_Lower']) / self.df['MA20'] # 假设中轨是MA20
        self.df = self.df[bandwidth <= max_bandwidth]
        self._log(f"波动收缩(带宽<{max_bandwidth:.1%})")
        return self
    
    # ==========================================
    # H. 窄幅震荡与变盘信号
    # ==========================================
    def filter_narrow_range(self, days=7):
        """
        NR7 形态：今日振幅是过去7天最小的 (即将变盘)
        需要 Backtrader 传入 'Range' (High-Low) 和 'MinRange7'
        """
        if 'Range' in self.df.columns and f'MinRange{days}' in self.df.columns:
            self.df = self.df[self.df['Range'] <= self.df[f'MinRange{days}']]
            self._log(f"NR{days}收缩形态")
        return self

    # ==========================================
    # I. 相对强弱与跑赢大盘
    # ==========================================
    def filter_relative_strength(self, benchmark_pct_change):
        """
        只选跑赢大盘的股票 (Alpha > 0)
        """
        if 'PrevClose' not in self.df.columns: return self
        
        stock_pct_change = (self.df['Close'] - self.df['PrevClose']) / self.df['PrevClose']
        
        # 股票涨幅 > 大盘涨幅
        self.df = self.df[stock_pct_change > benchmark_pct_change]
        self._log("相对强弱(跑赢大盘)")
        return self


    # ==========================================
    # J. 孕线与方向选择
    # ==========================================
    def filter_inside_bar(self):
        """
        孕线过滤：今日 High < 昨日 High 且 今日 Low > 昨日 Low
        代表多空力量暂时均衡，等待方向选择
        """
        cols = ['High', 'Low', 'PrevHigh', 'PrevLow']
        if not all(c in self.df.columns for c in cols): return self
        
        self.df = self.df[
            (self.df['High'] < self.df['PrevHigh']) &
            (self.df['Low'] > self.df['PrevLow'])
        ]
        self._log("Inside Bar形态")
        return self

    # ==========================================
    # K. 权重分配与风险平价
    # ==========================================
    def calculate_weights(self, method='equal'):
        """
        为筛选出的股票分配权重，并添加到 DataFrame 的 'Weight' 列
        :param method: 'equal' (等权) 或 'risk_parity' (波动率平价)
        """
        count = len(self.df)
        if count == 0: return self
        
        if method == 'equal':
            self.df['Weight'] = 1.0 / count
            
        elif method == 'risk_parity':
            # 波动率倒数加权：波动越小，权重越大
            # 假设已计算 1/ATR 作为因子
            inv_vol = 1.0 / self.df['ATR']
            total_inv_vol = inv_vol.sum()
            self.df['Weight'] = inv_vol / total_inv_vol
            
        return self