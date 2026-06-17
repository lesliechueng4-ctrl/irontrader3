"""
基于涨停股池的筹码质量分析（使用实时数据）
"""
from data_fetcher import DataFetcher

def test_realtime_pool():
    """测试使用涨停股池实时数据进行筹码分析"""
    
    print("=" * 60)
    print("测试涨停股池实时数据分析")
    print("=" * 60)
    
    # 初始化
    fetcher = DataFetcher()
    
    # 获取涨停股池
    print("\n正在获取涨停股池...")
    zt_pool = fetcher.get_limit_up_pool()
    
    if not zt_pool:
        print("今日无涨停股")
        return
    
    print(f"涨停股数量: {len(zt_pool)}")
    
    # 显示涨停股池可用字段
    print("\n[data_fetcher涨停股池字段]")
    sample = zt_pool[0]
    for key, value in sample.items():
        print(f"  - {key}: {type(value).__name__} = {value}")
    
    # 筛选高质量股票（基于涨停池数据）
    print("\n" + "=" * 60)
    print("基于涨停池数据的筛选逻辑")
    print("=" * 60)
    
    high_quality = []
    
    for stock in zt_pool:
        score = 0
        reasons = []
        
        # 筛选1：封单金额
        seal_amount = stock.get('seal_amount', 0)
        if seal_amount >= 100_0000_000:  # 1亿以上
            score += 3
            reasons.append(f"封单{seal_amount/100000000:.1f}亿，加3分")
        elif seal_amount >= 50_0000_000:  # 5000万以上
            score += 2
            reasons.append(f"封单{seal_amount/100000000:.1f}亿，加2分")
        elif seal_amount >= 19_0000_000:  # 1900万以上
            score += 1
            reasons.append(f"封单{seal_amount/100000000:.1f}亿，加1分")
        
        # 筛选2：连板数
        limit_count = stock.get('limit_count', 1)
        if limit_count >= 3:
            score += 2
            reasons.append(f"{limit_count}连板，加2分")
        elif limit_count >= 2:
            score += 1
            reasons.append(f"{limit_count}连板，加1分")
        
        # 筛选3：换手率
        turnover = stock.get('turnover_rate', 0) * 100  # 转为百分比
        if 8.0 <= turnover <= 20.0:
            score += 1
            reasons.append(f"良性换手{turnover:.1f}%，加1分")
        elif turnover > 35.0:
            score -= 1
            reasons.append(f"过度换手{turnover:.1f}%，扣1分")
        elif turnover > 0:
            reasons.append(f"换手率{turnover:.1f}%")
        
        # 筛选4：首次封板时间
        first_time = stock.get('first_limit_time', '')
        if first_time and first_time <= '09:30:00':
            score -= 2
            reasons.append("一字板，扣2分")
        elif first_time and '09:31' <= first_time <= '09:40:00':
            score += 1
            reasons.append("早盘封板，加1分")
        
        # 筛选5：涨幅
        change_pct = stock.get('change_pct', 0)
        if change_pct < 0:
            score -= 10
            reasons.append(f"下跌{change_pct:.2f}%，扣10分")
        elif change_pct > 9.0:
            reasons.append(f"涨停{change_pct:.2f}%")
        else:
            reasons.append(f"涨幅{change_pct:.2f}%")
        
        # 评分
        if score >= 5:
            quality = "[强烈推荐]"
        elif score >= 3:
            quality = "[推荐]"
        elif score >= 1:
            quality = "[观望]"
        else:
            quality = "[不推荐]"
        
        if score >= 3:
            high_quality.append({
                'code': stock['code'],
                'name': stock['name'],
                'score': score,
                'quality': quality,
                'reasons': reasons,
                'seal_amount': seal_amount,
                'limit_count': limit_count,
                'turnover_rate': turnover,
                'first_limit_time': first_time,
                'sector': stock.get('sector', '')
            })
    
    # 排序
    high_quality.sort(key=lambda x: x['score'], reverse=True)
    
    # 显示结果
    print(f"\n找到 {len(high_quality)} 只高质量股票（得分>=3）\n")
    
    for idx, stock in enumerate(high_quality[:10], 1):
        print(f"{'='*60}")
        print(f"#{idx} {stock['code']} {stock['name']} {stock['quality']}")
        print(f"  得分: {stock['score']}")
        print(f"  封单: {stock['seal_amount']/100000000:.2f}亿")
        print(f"  连板: {stock['limit_count']}天")
        print(f"  换手: {stock['turnover_rate']:.1f}%")
        print(f"  首封: {stock['first_limit_time']}")
        print(f"  板块: {stock['sector']}")
        print(f"\n  评分依据:")
        for reason in stock['reasons']:
            print(f"    - {reason}")
    
    # 统计
    print(f"\n{'='*60}")
    print("统计结果:")
    print(f"  涨停股总数: {len(zt_pool)}")
    print(f"  高质量股票数: {len(high_quality)}")
    print(f"  比例: {len(high_quality)/len(zt_pool)*100:.1f}%")
    
    # 按板块统计
    print(f"\n{'='*60}")
    print("板块热度统计:")
    
    sector_count = {}
    for stock in zt_pool:
        sector = stock.get('sector', '其他')
        if sector not in sector_count:
            sector_count[sector] = 0
        sector_count[sector] += 1
    
    # 排序
    sector_sorted = sorted(sector_count.items(), key=lambda x: x[1], reverse=True)
    
    print(f"  热门板块TOP10:")
    for idx, (sector, count) in enumerate(sector_sorted[:10], 1):
        bar = "█" * min(count // 2, 30)
        print(f"  {idx}. {sector}: {count}只 {bar}")

if __name__ == "__main__":
    test_realtime_pool()
