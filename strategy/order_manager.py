import datetime
import backtrader as bt
from utils.logger import Logger


class OrderManager:
    def __init__(self, strategy, debug=True):
        self.strat = strategy
        self.debug = debug
        self.logger = Logger()
        self.open_orders = {}

    def _log(self, txt, dt=None):
        if self.debug:
            dt = dt or self.strat.data.datetime.date(0)
            self.logger.debug(f"{dt} [订单] {txt}")

    def buy_market(self, data, size):
        if size == 0:
            return None
        self._log(f"提交市价买单: {data._name} 数量:{size}")
        order = self.strat.buy(data=data, size=size, exectype=bt.Order.Market)
        self._track_order(order, order_type='entries')
        return order

    def buy_stop(self, data, size, price, valid_days=None):
        if size == 0:
            return None
        valid = None
        if valid_days:
            valid = self.strat.data.datetime.date(0) + datetime.timedelta(days=valid_days)
        self._log(f"提交突破买单: {data._name} 触发价:{price:.2f}")
        order = self.strat.buy(
            data=data, size=size,
            exectype=bt.Order.Stop,
            price=price,
            valid=valid
        )
        self._track_order(order, order_type='entries')
        return order

    def sell_market(self, data, size=None):
        if size is None:
            pos_size = self.strat.getposition(data).size
            if pos_size > 0:
                self._log(f"市价清仓: {data._name} 数量:{pos_size}")
                order = self.strat.close(data)
                self._track_order(order, order_type='exits')
                return order
        else:
            self._log(f"市价卖出: {data._name} 数量:{size}")
            order = self.strat.sell(data=data, size=size, exectype=bt.Order.Market)
            self._track_order(order, order_type='exits')
            return order

    def update_trailing_stop(self, data, stop_price):
        self.cancel_all_orders(data, types=['exits'])
        size = self.strat.getposition(data).size
        if size > 0:
            order = self.strat.sell(
                data=data, size=size,
                exectype=bt.Order.Stop,
                price=stop_price
            )
            self._track_order(order, order_type='exits')
            return order
        return None

    def _track_order(self, order, order_type='entries'):
        name = order.data._name
        if name not in self.open_orders:
            self.open_orders[name] = {'entries': [], 'exits': []}
        self.open_orders[name][order_type].append(order)

    def has_pending_order(self, data):
        name = data._name
        if name in self.open_orders:
            for o in self.open_orders[name]['entries']:
                if o.status in [bt.Order.Submitted, bt.Order.Accepted]:
                    return True
        return False

    def cancel_all_orders(self, data, types=['entries', 'exits']):
        name = data._name
        if name not in self.open_orders:
            return
        for t in types:
            for o in self.open_orders[name][t][:]:
                if o.status in [bt.Order.Submitted, bt.Order.Accepted]:
                    self.strat.cancel(o)
                    self._log(f"撤单: {name} (类型:{t})")
            self.open_orders[name][t] = []

    def process_status(self, order):
        dt = self.strat.data.datetime.date(0)
        name = order.data._name
        if order.status == bt.Order.Completed:
            if order.isbuy():
                self.logger.log_trade(dt, "BUY", name, order.executed.price, order.executed.size, comm=order.executed.comm)
            else:
                self.logger.log_trade(dt, "SELL", name, order.executed.price, order.executed.size, pnl=order.executed.pnl, comm=order.executed.comm)
        elif order.status == bt.Order.Canceled:
            pass
        elif order.status == bt.Order.Rejected:
            self.logger.warning(f"订单被拒绝: {name}")
        elif order.status == bt.Order.Margin:
            self.logger.error(f"保证金不足，无法交易: {name}", exc_info=False)
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self._cleanup_tracking(order)

    def _cleanup_tracking(self, order):
        name = order.data._name
        if name in self.open_orders:
            for t in ['entries', 'exits']:
                if order in self.open_orders[name][t]:
                    self.open_orders[name][t].remove(order)
