# main.py (最终修正版)
import sys
import io
# 设置标准输出为 UTF-8 编码，解决 Windows 控制台 emoji 显示问题
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import backtrader as bt
import os
import datetime
import pandas as pd
import random
# 确保 strategies.py 在同一目录下
from strategies import ModularScreenerStrategy 

DATA_DIR = 'data'

# 控制每次参与回测的股票数量（不含 SPY）
# - 50: 前期快速测试 / 小样本
# - 100: 较平衡
# - None: 使用所有股
MAX_STOCKS = 100
# 是否对股票列表做随机打乱（推荐 True，避免按字母顺序导致行业偏差）
USE_RANDOM_SAMPLING = True

# 为了结果可复现，固定随机种子
RANDOM_SEED = 41

# 回测日期范围（请在此修改）
BACKTEST_FROM = datetime.datetime(2024, 6, 1)
BACKTEST_TO   = datetime.datetime(2026, 1, 1)
# 若某只股票的数据起始日晚于 (BACKTEST_FROM + 此天数)，则跳过该股，避免把整段回测拖到很晚
MAX_START_DAYS_AFTER = 60

def load_csv_data(file_path, fromdate, todate, require_start_near_fromdate=True):
    """加载CSV文件并转换为backtrader可用的格式"""
    try:
        # 尝试读取CSV，处理多header行的情况
        df = pd.read_csv(file_path, skiprows=2, index_col=0, parse_dates=True)
        
        # 检查列名，如果是多级索引格式，需要处理
        if 'Date' in df.columns or df.index.name == 'Date':
            # 如果Date是索引，重置索引
            if df.index.name == 'Date' or isinstance(df.index, pd.DatetimeIndex):
                df.reset_index(inplace=True)
                if 'Date' in df.columns:
                    df['Date'] = pd.to_datetime(df['Date'])
                    df.set_index('Date', inplace=True)
        
        # 确保列名正确（处理可能的列名变化）
        # 期望的列：Open, High, Low, Close, Volume
        column_mapping = {
            'Open': 'Open', 'open': 'Open', 'OPEN': 'Open',
            'High': 'High', 'high': 'High', 'HIGH': 'High',
            'Low': 'Low', 'low': 'Low', 'LOW': 'Low',
            'Close': 'Close', 'close': 'Close', 'CLOSE': 'Close', 'Price': 'Close',
            'Volume': 'Volume', 'volume': 'Volume', 'VOLUME': 'Volume'
        }
        
        # 重命名列
        df.rename(columns=column_mapping, inplace=True)
        
        # 确保有必要的列
        required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        if not all(col in df.columns for col in required_cols):
            # 如果列顺序不对，尝试按位置读取
            df = pd.read_csv(file_path, skiprows=3, header=None)
            # 假设格式：Date(0), Close(1), High(2), Low(3), Open(4), Volume(5)
            if len(df.columns) >= 6:
                df.columns = ['Date', 'Close', 'High', 'Low', 'Open', 'Volume'] + [f'col_{i}' for i in range(6, len(df.columns))]
                df['Date'] = pd.to_datetime(df['Date'])
                df.set_index('Date', inplace=True)
            else:
                raise ValueError(f"CSV格式不正确: {file_path}")
        
        # 筛选日期范围
        df = df[(df.index >= fromdate) & (df.index <= todate)]
        if len(df) == 0:
            return None
        # 若要求“起始日接近 fromdate”，则数据开始太晚的股票直接跳过，避免拖晚整段回测
        if require_start_near_fromdate:
            first_date = df.index.min()
            if hasattr(first_date, 'to_pydatetime'):
                first_date = first_date.to_pydatetime()
            if first_date > fromdate + datetime.timedelta(days=MAX_START_DAYS_AFTER):
                return None
        # 使用PandasData feed
        return bt.feeds.PandasData(
            dataname=df,
            datetime=None,  # 使用索引作为日期
            open='Open',
            high='High',
            low='Low',
            close='Close',
            volume='Volume',
            openinterest=-1
        )
    except Exception as e:
        # 如果pandas读取失败，尝试直接使用GenericCSVData（新格式）
        try:
            return bt.feeds.GenericCSVData(
                dataname=file_path,
                fromdate=fromdate,
                todate=todate,
                dtformat='%Y-%m-%d',
                headers=True,
                openinterest=-1,
                datetime=0, open=1, high=2, low=3, close=4, volume=5
            )
        except:
            raise e

def run_backtest():
    cerebro = bt.Cerebro()

    # 1. 检查数据目录是否存在
    if not os.path.exists(DATA_DIR) or len(os.listdir(DATA_DIR)) == 0:
        print(f"❌ 错误：'{DATA_DIR}' 目录下没有数据。")
        print("请先运行 data_manager.py 下载数据 (务必确保包含 SPY)。")
        return

    print("⏳ 正在加载数据到回测引擎...")
    
    # 2. 获取所有 CSV 文件列表
    # 过滤掉非 csv 文件
    all_files = [f for f in os.listdir(DATA_DIR) if f.endswith('.csv')]
    
    # =========================================================
    # 【核心修正】强制 SPY 成为 data0 (作为大盘风控基准)
    # =========================================================
    if 'SPY.csv' in all_files:
        print("✅ 发现 SPY，正在将其设为基准数据 (data0)...")
        spy_path = os.path.join(DATA_DIR, 'SPY.csv')
        
        # 加载 SPY（与回测区间一致）
        spy_data = load_csv_data(
            spy_path,
            fromdate=BACKTEST_FROM,
            todate=BACKTEST_TO,
            require_start_near_fromdate=False
        )
        if spy_data is None:
            print("❌ SPY 在指定日期范围内无数据。")
            return
        cerebro.adddata(spy_data, name='SPY')
        
        # 从待加载列表中移除 SPY，防止后面重复加载
        all_files.remove('SPY.csv')
    else:
        print("❌ 严重警告：在 data 目录下未找到 SPY.csv！")
        print("   策略的大盘风控将失效，或者会错误地使用第一只股票作为大盘。")
        print("   建议立即停止，先去下载 SPY 数据。")
        # 也可以选择 return 终止程序

    # =========================================================
    # 3. 加载其余股票
    # =========================================================
    # 此时 all_files 已经不包含 SPY.csv，只剩个股
    stock_files = all_files

    # 可选：随机抽样，避免总是偏向字母表前面的股票
    if USE_RANDOM_SAMPLING:
        random.seed(RANDOM_SEED)
        random.shuffle(stock_files)

    # 根据 MAX_STOCKS 控制样本规模
    if isinstance(MAX_STOCKS, int) and MAX_STOCKS > 0:
        target_files = stock_files[:MAX_STOCKS]
    else:
        target_files = stock_files
    
    print(f"📦 正在加载其余 {len(target_files)} 只股票数据...")
    
    success_count = 0
    for filename in target_files: 
        ticker = filename.split('.')[0]
        file_path = os.path.join(DATA_DIR, filename)
        
        try:
            data = load_csv_data(
                file_path,
                fromdate=BACKTEST_FROM,
                todate=BACKTEST_TO,
                require_start_near_fromdate=True
            )
            if data is None:
                continue  # 该股数据起始太晚，跳过，避免把回测拖到 24/25 年
            cerebro.adddata(data, name=ticker)
            success_count += 1
        except Exception as e:
            print(f"⚠️ 加载 {ticker} 失败: {e}")

    print(f"📊 数据加载完毕。总计加载: {len(cerebro.datas)} 只 (含 SPY)")

    # 4. 注入策略
    cerebro.addstrategy(ModularScreenerStrategy)

    # 5. 设置资金与佣金
    cerebro.broker.setcash(100000.0) # 10万美金初始资金
    cerebro.broker.setcommission(commission=0.0005) # 万分之五佣金

    # 6. 添加分析指标
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    # 7. 运行回测
    print("-" * 50)
    print(f"💰 初始资金: ${cerebro.broker.getvalue():,.2f}")
    print("🚀 开始回测 (Screener 正在逐日扫描)...")
    
    # runonce=False: 多标的(500+)且长度不一致时，runonce 易触发 IndexError，改用逐 bar 执行
    results = cerebro.run(runonce=False)
    strat = results[0]

    # 8. 输出统计结果
    end_val = cerebro.broker.getvalue()
    pnl = end_val - 100000.0
    
    # 安全获取分析结果
    sharpe_res = strat.analyzers.sharpe.get_analysis()
    sharpe = sharpe_res.get('sharperatio', 0)
    if sharpe is None: sharpe = 0 # 处理可能为 None 的情况
        
    max_dd = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    
    trades = strat.analyzers.trades.get_analysis()
    total_trades = trades.get('total', {}).get('total', 0)
    won_trades = trades.get('won', {}).get('total', 0)
    win_rate = (won_trades / total_trades * 100) if total_trades > 0 else 0

    print("-" * 50)
    print(f"📈 最终资金: ${end_val:,.2f}")
    print(f"💵 净利润:   ${pnl:,.2f} ({(pnl/100000)*100:.2f}%)")
    print(f"📐 夏普比率: {sharpe:.2f}")
    print(f"📉 最大回撤: {max_dd:.2f}%")
    print(f"🔢 总交易数: {total_trades}")
    print(f"🏆 胜率:     {win_rate:.2f}%")
    print("-" * 50)

if __name__ == '__main__':
    run_backtest()