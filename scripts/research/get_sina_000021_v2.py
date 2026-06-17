"""
从新浪财经接口获取股票实时行情（备用接口）
"""
import requests
import json
from datetime import datetime

def get_sina_realtime_v2(code):
    """
    使用新浪财经备用接口获取实时行情
    """
    # 新浪财经API v2
    # 格式: sz000021 (深市000021)
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
            'Accept': '*/*',
            'Referer': 'http://finance.sina.com.cn'
        }
        
        resp = requests.get(url, headers=headers, timeout=10, proxies={'http': None, 'https': None})
        
        if resp.status_code == 200:
            # 解析新浪返回的数据格式
            # 格式: var hq_str_sz000021="深科技,35.52,36.20,35.52,35.52,0.00,35.52,118434744,46389600,0.00,0,0.00,0,0,0,0,0,0.00,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0.00,0.00,0.00,2024-03-09,15:00:00,00";
            text = resp.text.strip()
            
            # 提取JSON部分
            if '=' in text:
                json_str = text.split('=', 1)[1].strip()
                # 去掉分号
                if json_str.endswith(';'):
                    json_str = json_str[:-1].strip()
                if json_str.startswith('"') and json_str.endswith('"'):
                    json_str = json_str[1:-1]
                
                # 分割数据
                parts = json_str.split(',')
                
                if len(parts) >= 32:
                    stock_name = parts[0]
                    open_price = float(parts[1])
                    pre_close = float(parts[2])
                    current = float(parts[3])
                    high = float(parts[4])
                    low = float(parts[5])
                    volume = int(float(parts[8]))  # 成交量（手）
                    amount = float(parts[9])  # 成交额（元）
                    
                    # 计算涨跌
                    if pre_close > 0:
                        change = current - pre_close
                        change_pct = (change / pre_close) * 100
                    else:
                        change = 0
                        change_pct = 0
                    
                    # 计算振幅
                    if open_price > 0:
                        amplitude = (high - low) / open_price * 100
                    else:
                        amplitude = 0
                    
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
                        'amplitude': amplitude,
                        'source': 'sina_v2'
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
print("从新浪财经获取000021深科技实时数据（备用接口）")
print("=" * 80)

data = get_sina_realtime_v2('000021')

if data:
    print("\n[OK] 数据获取成功！\n")
    print(f"股票代码: {data['code']}")
    print(f"股票名称: {data['name']}")
    print(f"当前价: {data['current']:.2f}")
    print(f"昨收价: {data['pre_close']:.2f}")
    print(f"开盘价: {data['open']:.2f}")
    print(f"最高价: {data['high']:.2f}")
    print(f"最低价: {data['low']:.2f}")
    print(f"涨跌幅: {data['change']:+.2f} ({data['change_pct']:+.2f}%)")
    print(f"今日振幅: {data['amplitude']:.2f}%")
    print(f"成交量: {data['volume']:,} 手")
    print(f"成交额: {data['amount']/100000000:.2f}亿元")
    
    # 判断涨跌
    if data['change_pct'] < 0:
        print(f"\n[状态] 跌 - {abs(data['change_pct']):.2f}%")
    elif data['change_pct'] > 0:
        print(f"\n[状态] 涨 + {data['change_pct']:.2f}%")
    else:
        print(f"\n[状态] 平盘")
    
    # 计算换手率（近似）
    if data['pre_close'] > 0 and data['volume'] > 0:
        # 假设流通盘为10亿（需要真实数据）
        estimated_turnover = (data['volume'] * 100 / 100000000000)  # 近似换手率
        print(f"估算换手: {estimated_turnover:.1f}%（基于假设流通盘）")
    
else:
    print("\n[FAIL] 数据获取失败！")

print("=" * 80)
