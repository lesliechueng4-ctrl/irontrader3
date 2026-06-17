# -*- coding: utf-8 -*-
"""使用新浪财经API获取002922实时数据"""
import requests

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
        
        resp = requests.get(url, headers=headers, timeout=10, proxies={'http': None, 'https': None})
        
        if resp.status_code == 200:
            text = resp.text.strip()
            
            if '=' in text:
                json_str = text.split('=', 1)[1].strip()
                if json_str.endswith(';'):
                    json_str = json_str[:-1].strip()
                
                parts = json_str.split(',')
                
                if len(parts) >= 32:
                    print(f"股票代码: {code}")
                    print(f"股票名称: {parts[0]}")
                    print(f"当前价: {float(parts[3]):.2f}")
                    print(f"昨收价: {float(parts[2]):.2f}")
                    print(f"开盘价: {float(parts[1]):.2f}")
                    print(f"最高价: {float(parts[4]):.2f}")
                    print(f"最低价: {float(parts[5]):.2f}")
                    print(f"涨跌额: {float(parts[3]) - float(parts[2]):+.2f}")
                    print(f"涨跌幅: {(float(parts[3]) - float(parts[2])) / float(parts[2]) * 100:+.2f}%")
                    print(f"成交量: {int(float(parts[6])):,} 手")
                    print(f"成交额: {float(parts[7])/100000000:.2f}亿元")
                    return parts
    except Exception as e:
        print(f"Error: {e}")

# 获取002922数据
print("=" * 60)
print("002922 实时数据（新浪财经）")
print("=" * 60)
get_sina_realtime('002922')
print("=" * 60)
