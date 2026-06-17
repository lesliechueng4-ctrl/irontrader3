"""
获取股票历史数据（使用新浪财经）
"""
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def get_sina_history(code, days=60):
    """
    使用新浪财经接口获取历史数据
    """
    from data_fetcher import DataFetcher
    df = DataFetcher()
    return df.get_stock_history(code, days=days)

# 测试
history = get_sina_history('000021', days=60)

if history is not None:
    print(f"Success: Got {len(history)} days of data")
    print(history.tail(10))
else:
    print("Failed to get data")
