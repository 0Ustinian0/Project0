"""通用辅助函数"""
import datetime


def parse_date(date_str):
    """YAML 日期字符串 -> datetime"""
    return datetime.datetime.strptime(str(date_str), "%Y-%m-%d")
