import logging
import os
import sys
import time
from datetime import datetime

# 统一前缀，便于在日志中区分模块
PREFIX_CONFIG = "[配置]"
PREFIX_DATA = "[数据]"
PREFIX_ENGINE = "[引擎]"
PREFIX_STRATEGY = "[策略]"
PREFIX_OPTIM = "[优化]"
PREFIX_ANALYSIS = "[分析]"
PREFIX_VALID = "[验证]"
PREFIX_RISK = "[风控]"


class Logger:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Logger, cls).__new__(cls)
        return cls._instance

    def __init__(self, log_dir='logs', file_name=None, console_level=logging.INFO, file_level=logging.DEBUG, quiet_console_init=False, retain_count=10):
        if hasattr(self, 'initialized'):
            return
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        use_timestamp = not file_name or file_name in (None, '')
        if use_timestamp:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_name = f"backtest_{timestamp}.log"
        self.log_path = os.path.join(log_dir, file_name)
        if use_timestamp and retain_count and retain_count > 0:
            self._clean_old_logs(log_dir, retain_count, self.log_path)
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
        if quiet_console_init:
            self.logger.debug(f"日志系统启动: {self.log_path}")
        else:
            self.info(f"{PREFIX_CONFIG} 日志: {self.log_path}")

    def _clean_old_logs(self, log_dir, retain_count, current_path):
        """保留最近 retain_count 个 backtest_*.log，删除更早的（本次会新建一个，故只保留 retain_count-1 个旧文件）。"""
        try:
            import glob
            pattern = os.path.join(log_dir, "backtest_*.log")
            files = [(f, os.path.getmtime(f)) for f in glob.glob(pattern) if os.path.isfile(f)]
            files.sort(key=lambda x: x[1], reverse=True)
            keep = max(0, retain_count - 1)
            to_remove = [f for f, _ in files[keep:]]
            for f in to_remove:
                if os.path.normpath(f) == os.path.normpath(current_path):
                    continue
                try:
                    os.remove(f)
                except OSError:
                    pass
        except Exception:
            pass

    def section(self, title):
        """输出分段标题，便于阅读。"""
        sep = "-" * 50
        self.logger.info("")
        self.logger.info(sep)
        self.logger.info(f"  {title}")
        self.logger.info(sep)

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
