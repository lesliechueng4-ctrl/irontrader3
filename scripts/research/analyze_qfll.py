"""
分析涨停股池中的QFLL股票
研究QFLL重仓股判断逻辑
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_fetcher import DataFetcher
import requests

print("=" * 80)
print("QFLL重仓股分析 - 002298 汉缆股份")
print("=" * 80)

# 1. 获取涨停股池
print("\n[1] 获取涨停股池...")
try:
    df = DataFetcher().get_limit_up_pool()
    
    if isinstance(df, list):
        stocks = df
    else:
        stocks = df.to_dict('records')
    
    print(f"   涨停股总数: {len(stocks)}")
except Exception as e:
    print(f"   [FAIL] {e}")
    sys.exit(1)

# 2. 筛选QFLL股票
print("\n[2] 筛选QFLL重仓股...")

# 方法1: 检查名称中是否包含QFII/QFLL
qfll_stocks = []
for stock in stocks:
    name = stock.get('name', '')
    if 'QFII' in name.upper() or 'QFLL' in name.upper():
        qfll_stocks.append(stock)
        
print(f"   在股票名称中找到QFII/QFLL: {len(qfll_stocks)}只")
for s in qfll_stocks:
    print(f"   - {s['code']} {s['name']}")

# 方法2: 通过新浪财经接口获取股东信息（包含QFLL）
print("\n[3] 通过新浪财经获取股东信息（查找QFLL）...")

def get_shareholders_sina(code):
    """
    通过新浪财经获取股东信息
    """
    try:
        url = f"http://vip.stock.finance.sina.com.cn/corp/go.php/vFD_FinancialGuideLine/stockid/{code}/displaytype/4.phtml"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': f'http://finance.sina.com.cn/stock/{code}.html'
        }
        
        resp = requests.get(url, headers=headers, timeout=10, proxies={'http': None, 'https': None})
        
        if resp.status_code == 200:
            text = resp.text
            
            # 查找QFII/QFLL
            if 'QFLL' in text or 'QFII' in text:
                return {
                    'has_qfll': True,
                    'source': 'sina_shareholders'
                }
            
            return {
                'has_qfll': False,
                'source': 'sina_shareholders'
            }
        else:
            return None
    except Exception as e:
        print(f"   Error fetching {code}: {e}")
        return None

# 测试002298
print(f"\n   测试002298汉缆股份...")
result = get_shareholders_sina('002298')
if result:
    print(f"   结果: {result}")
else:
    print(f"   未找到相关信息")

# 3. 获取更多涨停股的QFLL信息
print("\n[4] 批量检查涨停股的QFLL情况...")

# 获取前20只涨停股
top_stocks = stocks[:20]
qfll_results = []

for stock in top_stocks:
    code = stock['code']
    result = get_shareholders_sina(code)
    
    if result and result.get('has_qfll'):
        qfll_results.append({
            'code': code,
            'name': stock.get('name'),
            'has_qfll': True
        })

print(f"\n   找到QFLL重仓股: {len(qfll_results)}只")
for s in qfll_results:
    print(f"   - {s['code']} {s['name']}")

# 4. 研究QFLL是什么
print("\n[5] QFLL定义研究...")
print("""
   QFLL的可能含义：
   
   1. QFII (Qualified Foreign Institutional Investor)
      - 合格境外机构投资者
      - 外资通过特定渠道投资A股
      - 需要满足一定资质
   
   2. QFLL (Qualified Foreign Large-scale/Long-term?)
      - 合格境外大型/长期投资者？
      - 可能是QFII的延伸或特定分类
   
   3. 其他可能性：
      - QF (量化基金? Quantum Fund?)
      - LL (连续龙? Long-term Large?)
""")

# 5. 为什么QFLL股票容易出妖股
print("\n[6] 为什么QFLL股票容易出妖股？")
print("""
   [理论分析]
   
   1. 外资大鳄效应：
      - QFII/QFLL代表有实力的境外机构
      - 资金规模大、操作灵活
      - 容易形成趋势性行情
   
   2. 重仓锁定筹码：
      - 机构重仓意味着大量筹码被锁定
      - 市场流通筹码减少
      - 容易被少量资金推高
   
   3. 市场关注度：
      - 机构重仓股通常基本面较好
      - 吸引散户跟风
      - 资金聚集效应明显
   
   4. 政策红利：
      - 外资重仓可能受益于对外开放政策
      - 符合国家引进外资的方向
      - 容易获得政策支持
   
   [实战逻辑]
   
   1. 筹码集中度高：
      - 机构重仓=大量筹码锁定
      - 市场卖盘减少
      - 易于拉升
   
   2. 资金优势：
      - 境外资机构资金充裕
      - 可以持续推高股价
      - 容易形成主升浪
   
   3. 市场情绪：
      - 外资重仓=外资看好
      - 散户跟风买入
      - 形成正反馈循环
   
   4. 稳定性：
      - 机构不会轻易清仓
      - 持有周期长
      - 给足运作时间
""")

# 6. IronTrader中的判断逻辑
print("\n[7] IronTrader中的QFLL判断逻辑推测...")
print("""
   [可能的实现方式]
   
   1. 数据源检查：
      - 从新浪财经/东方财富获取股东信息
      - 解析股东列表，查找QFII/QFLL标识
      - 标记为QFLL重仓股
   
   2. AKShare接口：
      - ak.stock_individual_info_em(code=stock)
      - 返回股东结构信息
      - 检查是否有QFII/QFLL
   
   3. 龙虎榜匹配：
      - 龙虎榜中QFII持有个股
      - 重仓且为龙虎榜成员
      - 双重确认
   
   4. 实时数据：
      - 新浪财经实时行情中可能包含机构标识
      - 涨停时披露股东类型
      
   [可能的数据结构]
   
   示例：
   {
     'code': '002298',
     'name': '汉缆股份',
     'shareholders': [
       {'name': 'QFII', 'amount': xxx},
       {'name': 'QFLL', 'amount': xxx},
       {'name': '社保基金', 'amount': xxx},
       ...
     ],
     'is_qfll_heavy': True  # QFLL重仓标识
   }
""")

# 7. 总结
print("\n[8] 总结")
print(f"""
   当前涨停股池: {len(stocks)}只
   QFLL重仓股数量: {len(qfll_results)}只（基于名称匹配）
   实际QFLL重仓股: 需要通过股东信息进一步确认
   
   [关键发现]
   
   1. QFLL很可能是合格境外机构投资者(QFII)的延伸
   2. QFLL重仓股具有筹码集中+资金优势的特点
   3. 容易出妖股的原因：
      - 筹码锁定度高
      - 机构资金充裕
      - 市场关注度高
   
   [IronTrader可能的实现]
   
   需要检查以下代码:
   - data_fetcher.py - 是否有获取股东信息的方法
   - stock_selector.py - 是否有筛选QFLL股票的逻辑
   - config files - 是否有QFLL配置参数
   
   [下一步]
   
   建议检查IronTrader的源代码，确认QFLL判断的具体实现方式。
""")

print("\n" + "=" * 80)
print("分析完成")
print("=" * 80)
