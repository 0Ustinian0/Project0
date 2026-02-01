# 集中管理回测相关导入与常量
import os
import backtrader as bt
from config.loader import ConfigLoader
from engine.backtest import BacktestEngine
from strategy.strategy import ModularScreenerStrategy
from analysis.performance import PerformanceAnalyzer
from analysis.visualizer import plot_equity_curve, plot_drawdown
from data.providers import get_sp500_tickers, download_data, download_spy

UNIVERSE_NAME = 'SP500'
DEFAULT_DATA_DIR = os.path.join('data', UNIVERSE_NAME)

__all__ = [
    'os', 'bt', 'ConfigLoader', 'BacktestEngine', 'ModularScreenerStrategy',
    'PerformanceAnalyzer', 'plot_equity_curve', 'plot_drawdown',
    'get_sp500_tickers', 'download_data', 'download_spy',
    'UNIVERSE_NAME', 'DEFAULT_DATA_DIR',
]
