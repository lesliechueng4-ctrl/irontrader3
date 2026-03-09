"""
IronTrader 增强版使用示例
展示如何使用整合了筹码质量风控+打分的决策引擎
"""

from decision_maker_enhanced import DecisionMakerEnhanced


def example_single_decision():
    """示例1：单只股票决策"""
    print("=" * 60)
    print("示例1：单只股票决策")
    print("=" * 60)
    
    # 初始化增强版决策引擎（启用筹码质量分析）
    decision_maker = DecisionMakerEnhanced(
        enable_chip_quality=True,
        chip_config={
            'n_lookback': 5,          # 考察期5天
            'turnover_min': 8.0,      # 良性换手8%-20%
            'turnover_max': 20.0,
            'turnover_high': 35.0,     # 过度换手>35%
            'max_amplitude': 8.0,      # 最大振幅8%
            'shadow_threshold': 3.0,    # 影线阈值3%
        }
    )
    
    # 获取涨停池
    zt_pool = decision_maker.data_fetcher.get_limit_up_pool()
    
    if not zt_pool:
        print("今日无涨停股，无法测试")
        return
    
    # 测试第一只涨停股
    test_code = zt_pool[0]['code']
    print(f"\n测试股票: {test_code} {zt_pool[0]['name']}\n")
    
    # 进行决策
    result = decision_maker.make_decision(test_code)
    
    # 显示结果
    print(f"决策结果: {result['decision']}")
    print(f"信心指数: {'⭐' * result['confidence']} ({result['confidence']}/5)")
    print(f"\n{result['reason']}")
    
    # 显示筹码质量（如果启用）
    if result.get('chip_quality'):
        cq = result['chip_quality']
        print(f"\n{'─'*60}")
        print("🎲 筹码质量分析:")
        print(f"   通过风控: {'✅' if cq['pass_risk_filter'] else '❌'}")
        print(f"   总得分: {cq['total_score']}")
        
        # 风控详情
        if not cq['pass_risk_filter']:
            print(f"\n   风控原因:")
            if not cq['filter_details']['filter1_chip_dirty']:
                print(f"     - {cq['filter_details']['filter1_reason']}")
            if not cq['filter_details']['filter2_yizi_burst']:
                print(f"     - {cq['filter_details']['filter2_reason']}")
        
        # 得分详情
        if cq['total_score'] > 0:
            print(f"\n   得分构成:")
            score1 = cq['score_details']['score1_limitup_quality']
            score2 = cq['score_details']['score2_weak_to_strong']
            if score1 != 0:
                print(f"     - 筹码质量: {score1} ({cq['score_details']['score1_reason']})")
            if score2 != 0:
                print(f"     - 弱转强: {score2} ({cq['score_details']['score2_reason']})")
    
    # 显示板块效应
    if result.get('sector_effect'):
        se = result['sector_effect']
        print(f"\n{'─'*60}")
        print("🔥 板块效应分析:")
        print(f"   板块名称: {se['sector_name']}")
        print(f"   涨停数量: {se['limit_up_count']}")
        print(f"   有板块效应: {'✅' if se['has_effect'] else '❌'}")
    
    # 显示套利推荐
    if result.get('arbitrage'):
        print(f"\n{'─'*60}")
        print(f"💡 20cm套利推荐:")
        for arb in result['arbitrage']:
            print(f"   {arb['code']} {arb['name']} ({arb['board_type']})")
    
    if result.get('arbitrage_tip'):
        print(f"\n{result['arbitrage_tip']}")


def example_batch_decision():
    """示例2：批量决策"""
    print("\n" + "=" * 60)
    print("示例2：批量决策")
    print("=" * 60)
    
    # 初始化
    decision_maker = DecisionMakerEnhanced(enable_chip_quality=True)
    
    # 获取涨停池
    zt_pool = decision_maker.data_fetcher.get_limit_up_pool()
    
    if len(zt_pool) < 10:
        print("涨停股数量不足，无法批量测试")
        return
    
    # 测试前10只
    test_codes = [s['code'] for s in zt_pool[:10]]
    print(f"\n批量决策股票数: {len(test_codes)}\n")
    
    # 批量决策
    results = decision_maker.batch_make_decision(test_codes)
    
    # 统计结果
    buy_count = sum(1 for r in results.values() if r['decision'] == 'BUY')
    ignore_count = len(results) - buy_count
    
    print(f"\n{'─'*60}")
    print("决策统计:")
    print(f"   BUY: {buy_count} 只")
    print(f"   IGNORE: {ignore_count} 只")
    
    # 显示BUY决策的股票
    print(f"\n{'─'*60}")
    print("BUY决策列表:")
    for code, result in results.items():
        if result['decision'] == 'BUY':
            stock_name = result.get('stock_info', {}).get('name', '')
            confidence = result['confidence']
            
            # 获取筹码得分
            chip_score = 0
            if result.get('chip_quality'):
                chip_score = result['chip_quality']['total_score']
            
            print(f"\n   {code} {stock_name}")
            print(f"     信心: {confidence}/5 {'⭐' * confidence}")
            print(f"     筹码得分: {chip_score}")
            print(f"     理由: {result['reason'][:50]}...")
    
    # 显示被忽略的股票（前3个原因）
    ignore_reasons = []
    for result in results.values():
        if result['decision'] == 'IGNORE':
            reason = result['reason']
            if reason not in ignore_reasons:
                ignore_reasons.append(reason)
    
    print(f"\n{'─'*60}")
    print("主要忽略原因:")
    for reason in ignore_reasons[:3]:
        count = sum(1 for r in results.values() if r['decision'] == 'IGNORE' and r['reason'] == reason)
        print(f"   - {reason[:60]}... ({count}只)")


def example_high_quality_candidates():
    """示例3：获取高质量候选标的"""
    print("\n" + "=" * 60)
    print("示例3：获取高质量候选标的")
    print("=" * 60)
    
    # 初始化
    decision_maker = DecisionMakerEnhanced(
        enable_chip_quality=True,
        chip_config={
            'n_lookback': 5,
            'turnover_min': 8.0,
            'turnover_max': 20.0,
            'turnover_high': 35.0
        }
    )
    
    # 获取涨停池
    zt_pool = decision_maker.data_fetcher.get_limit_up_pool()
    
    if len(zt_pool) < 10:
        print("涨停股数量不足，无法测试")
        return
    
    # 获取高质量候选
    test_codes = [s['code'] for s in zt_pool[:20]]  # 测试前20只
    print(f"\n候选股票数: {len(test_codes)}")
    print(f"最低筹码得分要求: 10\n")
    
    candidates = decision_maker.get_high_quality_candidates(test_codes, min_chip_score=10)
    
    if not candidates:
        print("未找到符合条件的候选")
        return
    
    print(f"找到 {len(candidates)} 只高质量候选\n")
    
    # 显示候选列表
    for idx, candidate in enumerate(candidates, 1):
        print(f"{'─'*60}")
        print(f"候选 #{idx}: {candidate['code']} {candidate['name']}")
        print(f"   筹码得分: {candidate['chip_score']}")
        print(f"   决策信心: {candidate['decision_confidence']}/5 {'⭐' * candidate['decision_confidence']}")
        print(f"   综合评分: {candidate['chip_score'] + candidate['decision_confidence']}")
        print(f"\n   决策理由:")
        print(f"   {candidate['reason']}")


def example_comparison():
    """示例4：对比启用/未启用筹码质量分析"""
    print("\n" + "=" * 60)
    print("示例4：对比启用/未启用筹码质量分析")
    print("=" * 60)
    
    # 获取涨停池
    test_fetcher = decision_maker.data_fetcher = DataFetcher()
    zt_pool = test_fetcher.get_limit_up_pool()
    
    if len(zt_pool) < 10:
        print("涨停股数量不足，无法测试")
        return
    
    test_codes = [s['code'] for s in zt_pool[:10]]
    
    print(f"\n测试股票数: {len(test_codes)}\n")
    
    # 不启用筹码质量
    print(f"{'─'*60}")
    print("方案A: 不启用筹码质量分析")
    print(f"{'─'*60}")
    
    dm_without = DecisionMakerEnhanced(enable_chip_quality=False)
    results_without = dm_without.batch_make_decision(test_codes)
    buy_count_without = sum(1 for r in results_without.values() if r['decision'] == 'BUY')
    
    print(f"BUY数量: {buy_count_without}/{len(test_codes)}")
    
    # 启用筹码质量
    print(f"\n{'─'*60}")
    print("方案B: 启用筹码质量分析")
    print(f"{'─'*60}")
    
    dm_with = DecisionMakerEnhanced(enable_chip_quality=True)
    results_with = dm_with.batch_make_decision(test_codes)
    buy_count_with = sum(1 for r in results_with.values() if r['decision'] == 'BUY')
    
    print(f"BUY数量: {buy_count_with}/{len(test_codes)}")
    
    # 对比分析
    print(f"\n{'='*60}")
    print("对比分析:")
    print(f"   不启用筹码质量: {buy_count_without}只BUY")
    print(f"   启用筹码质量: {buy_count_with}只BUY")
    print(f"   筛码质量过滤掉: {buy_count_without - buy_count_with}只股票")
    
    # 显示被过滤掉的股票
    if buy_count_without > buy_count_with:
        print(f"\n被筹码质量过滤的股票:")
        for code in test_codes:
            result_without = results_without[code]
            result_with = results_with[code]
            
            if result_without['decision'] == 'BUY' and result_with['decision'] == 'IGNORE':
                stock_name = result_without['stock_info']['name']
                reason = result_with['reason']
                print(f"   - {code} {stock_name}: {reason[:60]}...")


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("IronTrader 增强版 - 筹码质量风控+打分系统")
    print("=" * 60)
    
    try:
        # 示例1：单只股票决策
        example_single_decision()
        
        # 示例2：批量决策
        example_batch_decision()
        
        # 示例3：高质量候选
        example_high_quality_candidates()
        
        # 示例4：对比分析
        example_comparison()
        
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    from data_fetcher import DataFetcher
    main()
