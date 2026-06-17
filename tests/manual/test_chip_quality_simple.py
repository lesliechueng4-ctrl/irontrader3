"""
测试筹码质量策略（无emoji版本）
"""
import sys
# 设置输出编码
sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None

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
        print(f"\n[分析] 股票: {code}")
        result = strategy.analyze_stock(code, days=30)
        
        print(f"  名称: {result['name']}")
        print(f"  通过风控: {result['pass_risk_filter']}")
        print(f"  总得分: {result['total_score']}")
        print(f"  推荐: {result['recommendation']}")
        
        # 风控详情
        if not result['pass_risk_filter']:
            print(f"\n  [风控] 失败原因:")
            filter_details = result['filter_details']
            if not filter_details.get('filter1_chip_dirty_pass', True):
                print(f"    - {filter_details.get('filter1_reason', 'N/A')}")
            if not filter_details.get('filter2_yizi_burst_pass', True):
                print(f"    - {filter_details.get('filter2_reason', 'N/A')}")
        
        # 得分详情
        if result['total_score'] > 0:
            print(f"\n  [得分] 构成:")
            score_details = result['score_details']
            if score_details['score1_limitup_quality'] != 0:
                print(f"    - 筹码质量: {score_details['score1_limitup_quality']}")
                print(f"      理由: {score_details['score1_reason']}")
            if score_details['score2_weak_to_strong'] != 0:
                print(f"    - 弱转强: {score_details['score2_weak_to_strong']}")
                print(f"      理由: {score_details['score2_reason']}")
    
    # 批量分析测试
    print("\n" + "=" * 60)
    print("2. 批量分析测试")
    print("=" * 60)
    
    batch_results = strategy.batch_analyze(test_codes, days=30)
    
    print(f"\n批量分析完成，共 {len(batch_results)} 只股票")
    
    for code, result in batch_results.items():
        status = '[PASS]' if result['pass_risk_filter'] else '[FAIL]'
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
    
    # 打印参数总结
    print("\n[参数总结]")
    print("  使用的筹码质量参数:")
    print(f"    n_lookback: {config['n_lookback']} (考察期天数)")
    print(f"    turnover_min: {config['turnover_min']}% (良性换手下限)")
    print(f"    turnover_max: {config['turnover_max']}% (良性换手上限)")
    print(f"    turnover_high: {config['turnover_high']}% (过度换手阈值)")
    print(f"    max_amplitude: {config['max_amplitude']}% (最大日均振幅)")
    print(f"    shadow_threshold: {config['shadow_threshold']}% (影线阈值)")
    
    print("\n[data_fetcher可用字段]")
    print("  涨停股池包含的字段:")
    if zt_pool:
        sample = zt_pool[0]
        for key in sample.keys():
            print(f"    - {key}: {type(sample[key]).__name__}")

if __name__ == "__main__":
    main()
