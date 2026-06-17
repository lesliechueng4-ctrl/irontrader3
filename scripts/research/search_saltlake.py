"""
搜索盐湖股份的股票代码
"""
import requests

def search_stock_by_name(keyword):
    """通过新浪财经搜索股票"""
    url = f"http://suggest3.sinajs.cn/suggest/type=11,2,3&key={keyword}&name=suggestdata"
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*'
        }
        
        resp = requests.get(url, headers=headers, timeout=5, proxies={'http': None, 'https': None})
        
        if resp.status_code == 200:
            # 新浪返回格式：var result={"data":[{"code":"002123","name":"测试股"},...]...]}
            text = resp.text.strip()
            
            if 'data' in text:
                # 提取数据部分
                start_idx = text.find('data')
                if start_idx != -1:
                    data_str = text[start_idx:]
                    # 提取JSON数组
                    start = data_str.find('[')
                    end = data_str.rfind(']') + 1
                    
                    if start != -1 and end > 0:
                        json_str = data_str[start:end]
                        
                        # 使用json模块解析
                        import json
                        data = json.loads(json_str)
                        
                        return data
        return []
    except:
        return []

print("=" * 80)
print("搜索盐湖股份")
print("=" * 80)

results = search_stock_by_name('盐湖股份')

if results:
    print(f"\n[OK] 找到 {len(results)} 只相关股票\n")
    
    for i, stock in enumerate(results[:10], 1):
        code = stock.get('code', '')
        name = stock.get('name', '')
        pinyin = stock.get('pinyin', '')
        
        print(f"\n{i}. {code} {name}")
        if pinyin:
            print(f"   拼音: {pinyin}")
        
        if '盐湖' in name:
            print(f"   [目标] 找到匹配股票！")
            target_code = code
            target_name = name
else:
    print("\n[X] 未找到相关股票")

print("\n" + "=" * 80)
print("搜索完成")
print("=" * 80)

if results:
    print("\n[提示] 如果找到盐湖股份，可以进一步分析：")
    print("1. 获取实时行情")
    print("2. 获取历史K线")
    print("3. 分析走势特征")
