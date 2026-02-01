"""加载 config/settings.yaml 配置"""
import os
import yaml
import datetime

def parse_date(date_str):
    """字符串转 datetime"""
    return datetime.datetime.strptime(str(date_str), "%Y-%m-%d")

class ConfigLoader:
    def __init__(self, config_path=None):
        if config_path is None:
            _dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(_dir, 'settings.yaml')
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"配置文件未找到: {config_path}")
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

    def get_backtest_config(self):
        """获取回测配置，并转换日期为 datetime"""
        bt_conf = dict(self.config.get('backtest', {}))
        if 'start_date' in bt_conf:
            bt_conf['start_date'] = parse_date(bt_conf['start_date'])
        if 'end_date' in bt_conf:
            bt_conf['end_date'] = parse_date(bt_conf['end_date'])
        return bt_conf

    def get_strategy_config(self):
        """获取策略参数"""
        return self.config.get('strategy', {})
