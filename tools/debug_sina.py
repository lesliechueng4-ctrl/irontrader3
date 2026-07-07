"""测试新浪接口是否可用（临时调试脚本，从项目根目录的模块导入）"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

print("=" * 60)
print("测试新浪财经接口")
print("=" * 60)

# 测试 1：wash_pattern_scanner 的新浪接口
print("\n[测试 1] 使用 wash_pattern_scanner 获取股票池...")
try:
    from wash_pattern_scanner import get_stock_pool
    stock_list = get_stock_pool("all_a", pool_source="sina")
    if stock_list:
        print(f"✅ 成功获取 {len(stock_list)} 只股票")
        print(f"   示例：{stock_list[0].code} - {stock_list[0].name}")
    else:
        print("❌ 返回空列表")
except Exception as e:
    print(f"❌ 失败: {e}")
    import traceback
    traceback.print_exc()

# 测试 2：DataFetcher 的新浪接口
print("\n[测试 2] 使用 DataFetcher 获取个股实时数据...")
try:
    from data_fetcher import DataFetcher
    fetcher = DataFetcher()

    # 测试获取平安银行
    stock_data = fetcher.get_stock_realtime('000001')
    if stock_data:
        print(f"✅ 成功获取股票数据")
        print(f"   代码: {stock_data.get('code')}")
        print(f"   名称: {stock_data.get('name')}")
        print(f"   价格: {stock_data.get('current')}")
        print(f"   涨跌幅: {stock_data.get('change_pct')}%")
    else:
        print("❌ 返回空数据")
except Exception as e:
    print(f"❌ 失败: {e}")
    import traceback
    traceback.print_exc()

# 测试 3：直接测试新浪 URL
print("\n[测试 3] 直接访问新浪接口...")
try:
    import requests
    url = "http://hq.sinajs.cn/list=s_sh000001"
    headers = {
        'Referer': 'http://finance.sina.com.cn',
        'User-Agent': 'Mozilla/5.0'
    }
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code == 200 and response.text:
        print(f"✅ 新浪接口响应成功")
        print(f"   返回数据: {response.text[:100]}...")
    else:
        print(f"❌ 响应异常: {response.status_code}")
except Exception as e:
    print(f"❌ 失败: {e}")

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)
