import logging
import os
import sys
import time
from datetime import datetime


class Logger:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Logger, cls).__new__(cls)
        return cls._instance

    def __init__(self, log_dir='logs', file_name=None, console_level=logging.INFO, file_level=logging.DEBUG):
        if hasattr(self, 'initialized'):
            return
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        if not file_name:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_name = f"backtest_{timestamp}.log"
        self.log_path = os.path.join(log_dir, file_name)
        self.logger = logging.getLogger('QuantSystem')
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers = []
        file_handler = logging.FileHandler(self.log_path, encoding='utf-8')
        file_handler.setLevel(file_level)
        file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(module)s: %(message)s'))
        self.logger.addHandler(file_handler)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(console_level)
        console_handler.setFormatter(logging.Formatter('%(message)s'))
        self.logger.addHandler(console_handler)
        self.start_time = time.time()
        self.last_progress_update = 0
        self.initialized = True
        self.info(f"📝 日志系统启动: {self.log_path}")

    def info(self, msg):
        self.logger.info(msg)

    def debug(self, msg):
        self.logger.debug(msg)

    def warning(self, msg):
        self.logger.warning(f"⚠️ {msg}")

    def log_trade(self, dt, action, ticker, price, size, pnl=0.0, comm=0.0):
        pnl_str = f"| PnL: {pnl:+.2f}" if pnl != 0 else ""
        msg = f"🛒 [TRADE] {dt} | {action:<4} | {ticker:<5} | @{price:.2f} | Vol:{size} | Comm:{comm:.2f} {pnl_str}"
        self.logger.info(msg)

    def error(self, msg, exc_info=True):
        self.logger.error(f"❌ {msg}", exc_info=exc_info)

    def log_performance(self, task_name, start_time):
        duration = time.time() - start_time
        self.logger.debug(f"⏱️ [PERF] {task_name} 耗时: {duration:.4f}s")

    def show_progress(self, current_dt, total_days=None):
        now = time.time()
        if now - self.last_progress_update > 1.0:
            sys.stdout.write(f"\r⏳ 回测进行中... 当前日期: {current_dt.date()}")
            sys.stdout.flush()
            self.last_progress_update = now
