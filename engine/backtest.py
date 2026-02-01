import time
import logging
import backtrader as bt
from data.manager import load_data_into_cerebro
from utils.logger import Logger


class BacktestEngine:
    def __init__(self, quick_mode=False, data=None, strategy=None, strategy_params=None,
                 initial_capital=100000.0, commission=0.0005, slippage=0.0):
        self.log_sys = Logger(console_level=logging.INFO if not quick_mode else logging.WARNING)
        self.cerebro = bt.Cerebro(runonce=True, preload=True, stdstats=False)
        self.cerebro.broker.set_checksubmit(checksubmit=False)
        self.cerebro.broker.set_eosbar(False)
        if data is not None and strategy is not None:
            self.set_capital(initial_capital)
            self.set_costs(commission=commission, slippage=slippage)
            self.load_data(
                data_dir=data['data_dir'],
                from_date=data['from_date'],
                to_date=data['to_date'],
                universe_size=data.get('universe_size'),
            )
            self.add_strategy(strategy, **(strategy_params or {}))
            self.add_analyzer(bt.analyzers.SharpeRatio, _name='sharpe')
            self.add_analyzer(bt.analyzers.DrawDown, _name='drawdown')
            self.add_analyzer(bt.analyzers.TradeAnalyzer, _name='trades')
            self.add_analyzer(bt.analyzers.TimeReturn, _name='returns')

    def set_capital(self, initial_cash=100000.0):
        self.cerebro.broker.setcash(initial_cash)

    def set_costs(self, commission=0.0005, slippage=0.0005):
        self.cerebro.broker.setcommission(commission=commission)
        self.cerebro.broker.set_slippage_perc(
            perc=slippage,
            slip_open=True,
            slip_match=True,
            slip_out=False
        )

    def load_data(self, data_dir, from_date, to_date, universe_size=None):
        t0 = time.time()
        self.log_sys.info(f"⏳ [引擎] 正在预加载数据 ({from_date.date()} ~ {to_date.date()})...")
        load_data_into_cerebro(
            self.cerebro,
            data_dir,
            from_date,
            to_date,
            universe_size=universe_size,
            logger=self.log_sys
        )
        self.log_sys.log_performance("Data Loading", t0)

    def add_strategy(self, strategy_cls, **kwargs):
        self.cerebro.addstrategy(strategy_cls, **kwargs)

    def add_analyzer(self, analyzer_cls, _name, **kwargs):
        self.cerebro.addanalyzer(analyzer_cls, _name=_name, **kwargs)

    def run(self):
        print("-" * 50)
        print(f"🚀 [引擎] 启动回测 | 初始资金: ${self.cerebro.broker.get_cash():,.2f}")
        print("-" * 50)
        runonce = len(self.cerebro.datas) <= 200
        results = self.cerebro.run(runonce=runonce)
        print("-" * 50)
        print(f"🏁 [引擎] 回测结束 | 最终资金: ${self.cerebro.broker.get_value():,.2f}")
        print("-" * 50)
        return results[0]
