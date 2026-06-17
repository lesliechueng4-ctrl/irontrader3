"""
调整参数后的涨停股池分析
"""
from data_fetcher import DataFetcher

def test_adjusted_scoring():
    """测试调整参数后的评分逻辑"""
    
    print("=" * 60)
    print("调整参数后的涨停股池分析")
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
    
    # 调整后的评分参数
    PARAMS = {
        'seal_1e9': 5,           # 封单1亿以上加5分
        'seal_5e8': 3,           # 封单5000万以上加3分
        'seal_2e8': 1,           # 封单2000万以上加1分
        'limit_count_gte3': 3,     # 3连板以上加3分
        'limit_count_eq2': 2,       # 2连板加2分
        'limit_count_eq1': 1,       # 1连板加1分
        'turnover_good_min': 5.0,    # 良性换手下限5%（降低从8%）
        'turnover_good_max': 25.0,   # 良性换手上限25%（提高从20%）
        'turnover_high': 40.0,       # 过度换手阈值40%（提高从35%）
        'yizi_penalty': -3,         # 一字板扣3分（降低从-2或-5）
    }
    
    print(f"\n[评分参数]")
    print(f"  封单1亿+: +{PARAMS['seal_1e9']}分")
    print(f"  封单5000万+: +{PARAMS['seal_5e8']}分")
    print(f"  封单2000万+: +{PARAMS['seal_2e8']}分")
    print(f"  3连板+: +{PARAMS['limit_count_gte3']}分")
    print(f"  2连板+: +{PARAMS['limit_count_eq2']}分")
    print(f"  1连板+: +{PARAMS['limit_count_eq1']}分")
    print(f"  良性换手{PARAMS['turnover_good_min']}%-{PARAMS['turnover_good_max']}%: +1分")
    print(f"  过度换手>{PARAMS['turnover_high']}%: -1分")
    print(f"  一字板: {PARAMS['yizi_penalty']}分")
    
    # 分析并打分
    scored_stocks = []
    
    for stock in zt_pool:
        score = 0
        reasons = []
        
        # 1. 封单金额评分
        seal_amount = stock.get('seal_amount', 0)
        if seal_amount >= 1_0000_0000:  # 1亿
            score += PARAMS['seal_1e9']
            reasons.append(f"封单{seal_amount/100000000:.1f}亿，+{PARAMS['seal_1e9']}分")
        elif seal_amount >= 5_0000_000:  # 5000万
            score += PARAMS['seal_5e8']
            reasons.append(f"封单{seal_amount/100000000:.1f}亿，+{PARAMS['seal_5e8']}分")
        elif seal_amount >= 2_0000_000:  # 2000万
            score += PARAMS['seal_2e8']
            reasons.append(f"封单{seal_amount/100000000:.1f}亿，+{PARAMS['seal_2e8']}分")
        
        # 2. 连板数评分
        limit_count = stock.get('limit_count', 1)
        if limit_count >= 3:
            score += PARAMS['limit_count_gte3']
            reasons.append(f"{limit_count}连板，+{PARAMS['limit_count_gte3']}分")
        elif limit_count == 2:
            score += PARAMS['limit_count_eq2']
            reasons.append(f"{limit_count}连板，+{PARAMS['limit_count_eq2']}分")
        elif limit_count == 1:
            score += PARAMS['limit_count_eq1']
            reasons.append(f"{limit_count}连板，+{PARAMS['limit_count_eq1']}分")
        
        # 3. 换手率评分
        turnover = stock.get('turnover_rate', 0) * 100  # 转换为百分比
        if PARAMS['turnover_good_min'] <= turnover <= PARAMS['turnover_good_max']:
            score += 1
            reasons.append(f"良性换手{turnover:.1f}%，+1分")
        elif turnover > PARAMS['turnover_high']:
            score -= 1
            reasons.append(f"过度换手{turnover:.1f}%，-1分")
        elif turnover > 0:
            reasons.append(f"换手率{turnover:.1f}%")
        
        # 4. 首次封板时间评分
        first_time = stock.get('first_limit_time', '')
        # 处理格式：可能是"092500"或"09:25:00"
        first_time_clean = first_time.replace(':', '')
        
        # 尝试解析时间
        try:
            if len(first_time_clean) == 6:
                hour = int(first_time_clean[:2])
                minute = int(first_time_clean[2:4])
                
                # 一字板（09:25-09:30）
                if hour == 9 and 25 <= minute <= 30:
                    score += PARAMS['yizi_penalty']
                    reasons.append(f"一字板（{first_time[:2]}:{first_time[2:4]}），{PARAMS['yizi_penalty']}分")
                # 早盘强力封板（09:30-09:40）
                elif hour == 9 and 30 <= minute <= 40:
                    score += 1
                    reasons.append(f"早盘封板（{first_time[:2]}:{first_time[2:4]}），+1分")
        except:
            pass
        
        # 5. 涨幅评分
        change_pct = stock.get('change_pct', 0)
        if change_pct < 0:
            score -= 10
            reasons.append(f"下跌{change_pct:.2f}%，-10分")
        elif change_pct >= 9.0:
            reasons.append(f"涨停{change_pct:.2f}%")
        else:
            reasons.append(f"涨幅{change_pct:.2f}%")
        
        # 评级
        if score >= 8:
            quality = "[强烈推荐] ★★★★★"
        elif score >= 6:
            quality = "[推荐] ★★★"
        elif score >= 4:
            quality = "[谨慎参与] ★★"
        elif score >= 2:
            quality = "[观望] ★"
        else:
            quality = "[不推荐]"
        
        scored_stocks.append({
            'code': stock['code'],
            'name': stock['name'],
            'score': score,
            'quality': quality,
            'reasons': reasons,
            'seal_amount': seal_amount,
            'limit_count': limit_count,
            'turnover': turnover,
            'first_limit_time': first_time,
            'sector': stock.get('sector', '')
        })
    
    # 按得分排序
    scored_stocks.sort(key=lambda x: x['score'], reverse=True)
    
    # 显示TOP20
    print(f"\n{'='*60}")
    print(f"TOP20 评分排序结果")
    print(f"{'='*60}\n")
    
    for idx, stock in enumerate(scored_stocks[:20], 1):
        print(f"{idx:2d}. {stock['code']} {stock['name']} {stock['quality']}")
        print(f"     得分: {stock['score']} | 封单:{stock['seal_amount']/100000000:.2f}亿 | 连板:{stock['limit_count']} | 换手:{stock['turnover']:.1f}% | 首封:{stock['first_limit_time']} | 板块:{stock['sector']}")
        print(f"     评分依据:")
        for reason in stock['reasons'][:5]:
            print(f"       - {reason}")
        print()
    
    # 统计
    print(f"{'='*60}")
    print("统计结果:")
    print(f"  涨停股总数: {len(zt_pool)}")
    print(f"  强烈推荐(>=8分): {len([s for s in scored_stocks if s['score'] >= 8])}")
    print(f"  推荐(>=6分): {len([s for s in scored_stocks if s['score'] >= 6])}")
    print(f"  谨慎参与(>=4分): {len([s for s in scored_stocks if s['score'] >= 4])}")
    print(f"  观望(>=2分): {len([s for s in scored_stocks if s['score'] >= 2])}")
    
    # 板块统计
    print(f"\n{'='*60}")
    print("板块热度TOP10:")
    
    sector_count = {}
    for stock in zt_pool:
        sector = stock.get('sector', '其他')
        if sector not in sector_count:
            sector_count[sector] = 0
        sector_count[sector] += 1
    
    sector_sorted = sorted(sector_count.items(), key=lambda x: x[1], reverse=True)
    
    for idx, (sector, count) in enumerate(sector_sorted[:10], 1):
        bar = "█" * min(count // 2, 30)
        print(f"  {idx}. {sector}: {count}只 {bar}")

if __name__ == "__main__":
    test_adjusted_scoring()
