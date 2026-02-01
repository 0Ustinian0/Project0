import yfinance as yf
import pandas as pd
import os
import requests
import io # 新增：用于处理字符串流

DATA_DIR = 'data'

def get_sp500_tickers():
    """从维基百科获取S&P 500成分股列表 (带伪装头)"""
    print("正在获取 S&P 500 成分股列表...")
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    
    # 【核心修复】伪装成浏览器
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        # 1. 先用 requests 获取网页内容
        response = requests.get(url, headers=headers)
        response.raise_for_status() # 检查是否请求成功
        
        # 2. 用 pandas 读取网页内容 (将文本转为文件流)
        tables = pd.read_html(io.StringIO(response.text))
        df = tables[0]
        
        tickers = df['Symbol'].tolist()
        # 修正一些特殊的符号，比如 BRK.B -> BRK-B (Yahoo 使用连字符)
        tickers = [t.replace('.', '-') for t in tickers]
        
        print(f"✅ 获取成功，共 {len(tickers)} 只股票。")
        return tickers
        
    except Exception as e:
        print(f"❌ 获取列表失败: {e}")
        print("⚠️ 将使用默认的科技股列表作为备选...")
        # 备选列表 (如果维基百科彻底挂了)
        return ['NVDA', 'AMD', 'TSLA', 'AAPL', 'MSFT', 'AMZN', 'GOOG', 'META', 'NFLX', 'PLTR', 'COIN', 'MARA']

def download_data(tickers, start_date='2017-01-01', end_date='2026-01-01'):
    """批量下载数据并保存为CSV"""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    
    print(f"开始下载数据 ({start_date} 至 {end_date})...")
    print(f"目标股票数: {len(tickers)} (注意: 全量下载可能需要 5-10 分钟)")
    
    # 批量下载比循环下载快很多
    # auto_adjust=True 处理拆股和分红
    # threads=True 开启多线程下载
    data = yf.download(tickers, start=start_date, end=end_date, group_by='ticker', auto_adjust=True, threads=True)
    
    success_count = 0
    
    # yfinance 批量下载返回的 DataFrame 结构比较复杂，需要处理
    # 如果只有1只股票，data 列是 (Open, High...), 如果多只，是 (Price, Ticker) 多级索引
    
    if len(tickers) == 1:
        # 单只股票处理
        ticker = tickers[0]
        try:
            if not data.empty:
                file_path = os.path.join(DATA_DIR, f"{ticker}.csv")
                # 重新排列列为 backtrader 格式：Date, Open, High, Low, Close, Volume
                df_formatted = data[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
                df_formatted.reset_index(inplace=True)
                df_formatted.to_csv(file_path, index=False, header=True)
                success_count += 1
        except:
            pass
    else:
        # 多只股票处理
        for ticker in tickers:
            try:
                # 提取该股票的数据 (假设是多级索引)
                df = data[ticker].dropna()
                
                # 数据清洗：如果数据太少（比如刚上市），则丢弃
                if len(df) < 200:
                    continue
                
                # 重新排列列为 backtrader 格式：Date, Open, High, Low, Close, Volume
                df_formatted = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
                df_formatted.reset_index(inplace=True)
                
                # 保存到 CSV (backtrader 期望的格式：Date, Open, High, Low, Close, Volume)
                file_path = os.path.join(DATA_DIR, f"{ticker}.csv")
                df_formatted.to_csv(file_path, index=False, header=True)
                success_count += 1
            except Exception as e:
                print(f"⚠️ 处理 {ticker} 失败: {e}")
                pass
            
    print(f"🎉 下载完成！成功保存 {success_count} 只股票数据到 '{DATA_DIR}/' 目录。")

if __name__ == '__main__':
    # 1. 获取列表
    tickers = get_sp500_tickers()
    
    # 2. 如果你想先测试一下，可以只取前 50 只跑跑看
    # print("测试模式：只下载前 50 只股票...")
    # tickers = tickers[:50] 
    
    # 3. 运行下载
    download_data(tickers)