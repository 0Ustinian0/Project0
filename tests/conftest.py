"""pytest 配置：保证从项目根目录可导入各模块"""
import sys
import os

# 将项目根目录加入 path，便于 tests 内 import strategy / portfolio 等
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)
