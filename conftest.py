"""pytest 根配置。

确保仓库根目录在 sys.path 中，使测试可直接导入顶层模块
（data_fetcher、decision_maker、config 等），无论 pytest 从何处调用。
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
