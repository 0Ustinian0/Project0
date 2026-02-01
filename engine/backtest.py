import time
import logging
import backtrader as bt
from data.manager import load_data_into_cerebro
from utils.logger import Logger
from engine.optimizer import run_optstrategy, _extract_metric, _params_to_dict


class BacktestEngine:
    def __init__(self, quick_mode=False, data=None, strategy=None, strategy_params=None,
                 initial_capital=100000.0, commission=0.0005, slippage=0.0):
        self.log_sys = Logger(console_level=logging.INFO if not quick_mode else logging.WARNING)
        self.cerebro = bt.Cerebro(runonce=True, preload=True, stdstats=False)
        self.cerebro.broker.set_checksubmit(checksubmit=False)
        self.cerebro.broker.set_eosbar(False)
        self._data = data
        self._initial_capital = initial_capital
        self._commission = commission
        self._slippage = slippage

        if data is not None:
            self.set_capital(initial_capital)
            self.set_costs(commission=commission, slippage=slippage)
            self.load_data(
                data_dir=data['data_dir'],
                from_date=data['from_date'],
                to_date=data['to_date'],
                universe_size=data.get('universe_size'),
                universe_seed=data.get('universe_seed'),
            )
            self._add_analyzers()
            if strategy is not None:
                params = dict(strategy_params or {})
                if 'data_dir' not in params and data is not None:
                    params['data_dir'] = data.get('data_dir')
                self.add_strategy(strategy, **params)

    def _add_analyzers(self):
        self.cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        self.cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        self.cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
        self.cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='returns')

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

    def load_data(self, data_dir, from_date, to_date, universe_size=None, universe_seed=None):
        t0 = time.time()
        self.log_sys.info(f"⏳ [引擎] 正在预加载数据 ({from_date.date()} ~ {to_date.date()})...")
        load_data_into_cerebro(
            self.cerebro,
            data_dir,
            from_date,
            to_date,
            universe_size=universe_size,
            universe_seed=universe_seed,
            logger=self.log_sys
        )
        self.log_sys.log_performance("Data Loading", t0)

    def add_strategy(self, strategy_cls, **kwargs):
        self.cerebro.addstrategy(strategy_cls, **kwargs)

    def add_optstrategy(self, strategy_cls, **param_grid):
        """参数网格：每个 key 对应一个 list，Backtrader 会对笛卡尔积逐一运行。"""
        self.cerebro.optstrategy(strategy_cls, **param_grid)

    def add_analyzer(self, analyzer_cls, _name, **kwargs):
        self.cerebro.addanalyzer(analyzer_cls, _name=_name, **kwargs)

    def run(self):
        self.log_sys.section("回测开始")
        self.log_sys.info(f"  🚀 初始资金: ${self.cerebro.broker.get_cash():,.2f}")
        # 多标的且长度不一致时 runonce 易触发 IndexError，仅单数据源时用 runonce 加速
        runonce = len(self.cerebro.datas) <= 1
        results = self.cerebro.run(runonce=runonce)
        self.log_sys.info(f"  🏁 最终资金: ${self.cerebro.broker.get_value():,.2f}")
        self.log_sys.info("")
        return results[0] if results else None

    def run_optimization(self, strategy_cls, param_grid, metric='sharperatio', maximize=True, composite_weights=None):
        """
        利用 Backtrader optstrategy 做网格搜索，返回最优参数字典、最优指标值、以及全部 (params, value) 列表。
        metric 为 "composite" 且 composite_weights 有值时，value 为多指标 dict，由调用方用 compute_composite_score 汇总排序。
        """
        grid = {k: v for k, v in param_grid.items() if isinstance(v, (list, tuple)) and not isinstance(v, str)}
        fixed = {k: v for k, v in param_grid.items() if k not in grid}
        if not grid:
            self.log_sys.warning("param_grid 中无 list 类型，无法进行网格搜索")
            return {}, None, []
        self.add_optstrategy(strategy_cls, **fixed, **grid)
        is_composite = (metric and metric.lower() == 'composite' and composite_weights)
        self.log_sys.info(f"  {_product_size(grid)} 组参数" + (" (综合指标)" if is_composite else "") + " ...")
        runonce = len(self.cerebro.datas) <= 1
        run_results = self.cerebro.run(runonce=runonce)
        strategies_flat = []
        for x in run_results:
            if isinstance(x, (list, tuple)):
                strategies_flat.extend(x)
            else:
                strategies_flat.append(x)
        results = []
        for strat in strategies_flat:
            params = _params_to_dict(strat)
            if is_composite:
                value = {k: _extract_metric(strat, k) for k in composite_weights}
                results.append((params, value))
            else:
                value = _extract_metric(strat, metric)
                results.append((params, value))
        if not is_composite:
            results.sort(key=lambda r: (r[1] if r[1] is not None else (float('-inf') if maximize else float('inf'))), reverse=maximize)
            best_params = results[0][0] if results else {}
            best_value = results[0][1] if results else None
        else:
            best_params, best_value = None, None
        return best_params, best_value, results


def _product_size(param_grid):
    import math
    return math.prod(len(v) for v in param_grid.values()) if param_grid else 0
