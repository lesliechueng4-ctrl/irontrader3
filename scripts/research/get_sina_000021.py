"""
从新浪财经接口获取股票实时行情
"""
import requests
import json
from datetime import datetime

def get_sina_realtime(code):
    """
    使用新浪财经直接接口获取实时行情
    不使用AKShare
    """
    # 新浪财经API
    # 6开头的用sh，其他用sz
    if code.startswith('6'):
        symbol = f"sh{code}"
    elif code.startswith('0') or code.startswith('3'):
        symbol = f"sz{code}"
    else:
        symbol = code
    
    url = f"http://hq.sinajs.cn/list={symbol}"
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*'
        }
        
        resp = requests.get(url, headers=headers, timeout=5)
        
        if resp.status_code == 200:
            # 解析新浪返回的数据格式
            # 格式: var hq_str_sh600519="贵州茅台,1855.00,1849.00,1855.00,1855.00,17358465,17358465,0,0,0.00,0,0.00,0,0,0,0.00,0,0.00,0,0.00,0,0.00,2024-03-09,15:00:00,00";
            data_str = resp.text
            data_str = data_str.split('=')[1].strip().strip('"').strip(';')
            
            # 分割数据
            parts = data_str.split(',')
            
            if len(parts) >= 32:
                stock_name = parts[0]
                current = float(parts[1])
                pre_close = float(parts[2])
                open_price = float(parts[3])
                high = float(parts[4])
                low = float(parts[5])
                volume = int(float(parts[6]))  # 手数
                amount = float(parts[7])  # 元
                
                # 计算涨跌
                if pre_close > 0:
                    change = current - pre_close
                    change_pct = (change / pre_close) * 100
                else:
                    change = 0
                    change_pct = 0
                
                return {
                    'code': code,
                    'name': stock_name,
                    'current': current,
                    'pre_close': pre_close,
                    'open': open_price,
                    'high': high,
                    'low': low,
                    'change': change,
                    'change_pct': change_pct,
                    'volume': volume,
                    'amount': amount,
                    'source': 'sina_direct'
                }
            
            return None
        else:
            print(f"HTTP Error: {resp.status_code}")
            return None
    except Exception as e:
        print(f"Request failed: {e}")
        return None

# 测试
print("=" * 80)
print("从新浪财经获取000021深科技实时数据")
print("=" * 80)

data = get_sina_realtime('000021')

if data:
    print("\n[OK] 数据获取成功！")
    print(f"\n股票代码: {data['code']}")
    print(f"股票名称: {data['name']}")
    print(f"当前价: {data['current']:.2f}")
    print(f"昨收价: {data['pre_close']:.2f}")
    print(f"开盘价: {data['open']:.2f}")
    print(f"最高价: {data['high']:.2f}")
    print(f"最低价: {data['low']:.2f}")
    print(f"涨跌幅: {data['change']:+.2f} ({data['change_pct']:+.2f}%)")
    print(f"成交量: {data['volume']:,} 手")
    print(f"成交额: {data['amount']/100000000:.2f}亿元")
    
    # 计算振幅
    if data['open'] > 0:
        amplitude = (data['high'] - data['low']) / data['open'] * 100
        print(f"今日振幅: {amplitude:.2f}%")
else:
    print("\n[FAIL] 数据获取失败！")

print("=" * 80)
