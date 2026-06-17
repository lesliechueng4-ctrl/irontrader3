"""
测试筹码质量策略集成
"""
from data_fetcher import DataFetcher
from chip_quality_strategy import ChipQualityStrategy

def main():
    print("=" * 60)
    print("测试筹码质量策略")
    print("=" * 60)
    
    # 初始化
    fetcher = DataFetcher()
    
    # 配置参数
    config = {
        'n_lookback': 5,
        'turnover_min': 8.0,
        'turnover_max': 20.0,
        'turnover_high': 35.0,
        'max_amplitude': 8.0,
        'shadow_threshold': 3.0
    }
    
    strategy = ChipQualityStrategy(fetcher, config)
    
    # 获取涨停池
    print("\n正在获取涨停股池...")
    zt_pool = fetcher.get_limit_up_pool()
    
    if not zt_pool:
        print("今日无涨停股，无法测试")
        return
    
    print(f"涨停股数量: {len(zt_pool)}")
    
    # 测试前3只股票
    test_codes = [s['code'] for s in zt_pool[:3]]
    
    print(f"\n测试股票: {test_codes}")
    
    # 单只股票测试
    print("\n" + "=" * 60)
    print("1. 单只股票测试")
    print("=" * 60)
    
    for code in test_codes:
        print(f"\n分析股票: {code}")
        result = strategy.analyze_stock(code, days=30)
        
        print(f"  名称: {result['name']}")
        print(f"  通过风控: {'✅' if result['pass_risk_filter'] else '❌'}")
        print(f"  总得分: {result['total_score']}")
        print(f"  推荐: {result['recommendation']}")
        
        # 风控详情
        if not result['pass_risk_filter']:
            print(f"\n  风控原因:")
            filter_details = result['filter_details']
            if not filter_details['filter1_chip_dirty']:
                print(f"    - {filter_details['filter1_reason']}")
            if not filter_details['filter2_yizi_burst']:
                print(f"    - {filter_details['filter2_reason']}")
        
        # 得分详情
        if result['total_score'] != 0:
            print(f"\n  得分详情:")
            score_details = result['score_details']
            if score_details['score1_limitup_quality'] != 0:
                print(f"    - 筹码质量: {score_details['score1_limitup_quality']}")
                print(f"      {score_details['score1_reason']}")
            if score_details['score2_weak_to_strong'] != 0:
                print(f"    - 弱转强: {score_details['score2_weak_to_strong']}")
                print(f"      {score_details['score2_reason']}")
    
    # 批量分析测试
    print("\n" + "=" * 60)
    print("2. 批量分析测试")
    print("=" * 60)
    
    batch_results = strategy.batch_analyze(test_codes, days=30)
    
    print(f"\n批量分析完成，共 {len(batch_results)} 只股票")
    
    for code, result in batch_results.items():
        status = '✅' if result['pass_risk_filter'] else '❌'
        print(f"  {status} {code} {result['name']} - 得分:{result['total_score']} - {result['recommendation']}")
    
    # 高质量股票测试
    print("\n" + "=" * 60)
    print("3. 高质量股票筛选测试")
    print("=" * 60)
    
    high_quality = strategy.get_high_quality_stocks(test_codes, min_score=0, days=30)
    
    print(f"\n高质量股票数量: {len(high_quality)}")
    
    if high_quality:
        print("\n高质量股票列表:")
        for stock in high_quality:
            print(f"\n  {stock['code']} {stock['name']}")
            print(f"    得分: {stock['score']}")
            print(f"    推荐: {stock['recommendation']}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

if __name__ == "__main__":
    main()
