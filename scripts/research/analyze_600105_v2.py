# -*- coding: utf-8 -*-
"""箱体突破分析：600105 永鼎股份"""

import requests
import pandas as pd
import numpy as np

def get_sina_realtime(code):
    """获取实时行情"""
    if code.startswith('6'):
        symbol = f"sh{code}"
    else:
        symbol = f"sz{code}"
    
    url = f"http://hq.sinajs.cn/list={symbol}"
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*'
        }
        
        resp = requests.get(url, headers=headers, timeout=5, proxies={'http': None, 'https': None})
        
        if resp.status_code == 200:
            text = resp.text.strip()
            
            if '=' in text:
                json_str = text.split('=', 1)[1].strip()
                if json_str.endswith(';'):
                    json_str = json_str[:-1].strip()
                
                parts = json_str.split(',')
                
                if len(parts) >= 32:
                    return {
                        'code': code,
                        'name': parts[0],
                        'current': float(parts[3]),
                        'pre_close': float(parts[2]),
                        'open': float(parts[1]),
                        'high': float(parts[4]),
                        'low': float(parts[5]),
                        'change': float(parts[3]) - float(parts[2]),
                        'change_pct': (float(parts[3]) - float(parts[2])) / float(parts[2]) * 100
                    }
        return None
    except:
        return None

print("=" * 80)
print("箱体突破分析：600105 永鼎股份")
print("=" * 80)

# 获取实时行情
print("\n[1] 获取实时行情...")
realtime = get_sina_realtime('600105')

if realtime:
    print("   [OK] 数据获取成功")
    print(f"\n股票代码: {realtime['code']}")
    print(f"股票名称: {realtime['name']}")
    print(f"当前价: {realtime['current']:.2f}")
    print(f"昨收价: {realtime['pre_close']:.2f}")
    print(f"开盘价: {realtime['open']:.2f}")
    print(f"最高价: {realtime['high']:.2f}")
    print(f"最低价: {realtime['low']:.2f}")
    print(f"涨跌幅: {realtime['change']:+.2f} ({realtime['change_pct']:+.2f}%)")
else:
    print("   [FAIL] 数据获取失败")
    exit(1)

# 简单判断
print("\n[2] 初步判断...")
print(f"   今日涨幅: {realtime['change_pct']:+.2f}%")

if realtime['change_pct'] > 3:
    print("   [状态] 大涨")
    print("   [建议] 可能是突破后拉升")
    print("   [风险] 追高风险高，谨慎介入")
elif realtime['change_pct'] > 0:
    print("   [状态] 小涨")
    print("   [建议] 观察能否站稳")
else:
    print("   [状态] 下跌/平盘")
    print("   [建议] 不符合突破特征")
    print("   [结论] 暂无箱体突破")

print("\n[3] 注意事项")
print("   [信息] 需要历史K线数据才能准确判断箱体")
print("   [信息] 建议使用通达信/同花顺等软件确认")
print("   [信息] 箱体判断需要：")
print("       - 近期多次触及的支撑/压力位")
print("       - 横盘整理的成交量变化")
print("       - 突破时的量能配合")

print("\n" + "=" * 80)
print("分析完成")
print("=" * 80)
