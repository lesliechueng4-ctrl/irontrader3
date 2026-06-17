"""
IronTrader Decision Maker Enhanced
增强版决策引擎 - 整合筹码质量风控+打分系统
"""

from typing import Dict, List
from data_fetcher import DataFetcher
from risk_engine import RiskEngine, MarketStateType
from stock_selector import StockSelector
from chip_quality_strategy import ChipQualityStrategy
from sector_money_flow import SectorMoneyFlowAnalyzer


class DecisionMakerEnhanced:
    """
    增强版决策引擎
    
    整合模块：
    1. RiskEngine - 市场五态风控
    2. StockSelector - 龙头选股
    3. ChipQualityStrategy - 筹码质量风控+打分（新增）
    """
    
    def __init__(self, enable_chip_quality: bool = True, chip_config: Dict = None):
        """
        初始化增强版决策引擎
        
        Args:
            enable_chip_quality: 是否启用筹码质量分析
            chip_config: 筹码质量策略配置
        """
        self.data_fetcher = DataFetcher()
        self.risk_engine = RiskEngine(self.data_fetcher)
        self.stock_selector = StockSelector(self.data_fetcher)
        self.sector_money_analyzer = SectorMoneyFlowAnalyzer(self.data_fetcher)
        
        # 筹码质量策略模块
        self.enable_chip_quality = enable_chip_quality
        if enable_chip_quality:
            self.chip_quality = ChipQualityStrategy(self.data_fetcher, chip_config)
            print("[增强决策] 筹码质量分析已启用")
        else:
            self.chip_quality = None
            print("[增强决策] 筹码质量分析未启用")
    
    def make_decision(self, code: str) -> Dict:
        """
        对个股做出决策（增强版）
        
        决策流程:
        1. 风控铁律检查 - 空仓态降级为WATCH+警告（不再拦截分析）
        2. 个股分析 - 涨停状态、封单金额
        3. 筹码质量检查（新增） - 剔除筹码脏了/一字板断层
        4. 可买性检查 - 一字板/秒板判定
        5. 板块效应检查 - 同板块涨停数
        6. 龙头判定 - 封单最大、连板最多
        7. 筹码打分（新增） - 换手板/弱转强确认
        
        Args:
            code: 股票代码
        Returns:
            {
                'decision': 'BUY' | 'IGNORE',
                'confidence': int,  # 1-5
                'reason': str,
                'market_state': Dict,
                'stock_info': Dict,
                'sector_effect': Dict,
                'chip_quality': Dict,  # 新增
                'arbitrage': List[Dict]
            }
        """
        # Step 1: 获取共享市场上下文
        zt_pool = self.data_fetcher.get_limit_up_pool()
        sector_map = self._build_sector_map(zt_pool)
        sector_money_map = self.data_fetcher.get_sector_money_flow_map()
        market_state = self.risk_engine.get_market_state(zt_pool=zt_pool)

        # 注：空仓态不再直接拦截分析，照常完整分析个股，
        # 最终由 _apply_market_gate 将 BUY 降级为 WATCH 并附加风控警告

        # Step 2: 个股分析
        stock_info = self.stock_selector.analyze_stock(code, zt_pool=zt_pool)
        
        if 'error' in stock_info:
            return self._ignore_result(
                code,
                f"❌ 数据错误: {stock_info['error']}",
                market_state,
                stock_info=stock_info,
                confidence=5
            )
        
        # Step 3: 涨停检查
        if not stock_info['is_limit_up']:
            return self._ignore_result(
                code,
                "⚠️ 股票未涨停，不符合龙头战法",
                market_state,
                stock_info=stock_info,
                confidence=3
            )
        
        # Step 4: 筹码质量检查（新增）
        if self.enable_chip_quality:
            pool_info = self._build_pool_context(
                code,
                stock_info,
                zt_pool,
                market_state.get('sentiment')
            )
            chip_quality_result = self.chip_quality.analyze_stock(code, days=30, pool_info=pool_info)
            
            if not chip_quality_result['pass_risk_filter']:
                # 筹码质量不通过，直接丢弃
                reasons = []
                filter_details = chip_quality_result['filter_details']
                
                # 修复字段名：filter1_chip_dirty_pass 而不是 filter1_chip_dirty
                if not filter_details.get('filter1_chip_dirty_pass', True):
                    reasons.append(filter_details['filter1_reason'])
                if not filter_details.get('filter2_yizi_burst_pass', True):
                    reasons.append(filter_details['filter2_reason'])
                
                return self._ignore_result(
                    code,
                    f"❌ 筹码质量风控: {'; '.join(reasons)}",
                    market_state,
                    stock_info=stock_info,
                    chip_quality=chip_quality_result,
                    confidence=4
                )
        else:
            chip_quality_result = None
        
        # Step 5: 可买性检查
        if not stock_info['is_buyable']:
            arbitrage = self.stock_selector.get_20cm_arbitrage(code)
            
            return self._ignore_result(
                code,
                f"⚠️ {stock_info['buyable_reason']}",
                market_state,
                stock_info=stock_info,
                chip_quality=chip_quality_result,
                arbitrage=arbitrage,
                arbitrage_tip='💡 建议：考虑以下20cm套利标的' if arbitrage else '',
                confidence=4
            )
        
        # Step 6: 板块效应检查
        sector_effect = self.stock_selector.check_sector_effect_fast(stock_info, sector_map)
        
        if not sector_effect['has_effect']:
            return self._ignore_result(
                code,
                f"⚠️ 板块效应不足: {sector_effect['sector_name']} 仅{sector_effect['limit_up_count']}只涨停（需≥3只）",
                market_state,
                stock_info=stock_info,
                chip_quality=chip_quality_result,
                sector_effect=sector_effect,
                confidence=3
            )

        sector_money = self.sector_money_analyzer.analyze_sector(
            sector_effect.get('sector_name', ''),
            zt_pool=zt_pool,
            money_flow_map=sector_money_map
        )
        if self.sector_money_analyzer.should_block_entry(
            sector_money,
            sector_effect.get('limit_up_count', 0)
        ):
            return self._ignore_result(
                code,
                f"⚠️ 板块资金确认不足: {sector_money.get('reason', '')}",
                market_state,
                stock_info=stock_info,
                chip_quality=chip_quality_result,
                sector_effect=sector_effect,
                sector_money=sector_money,
                confidence=3
            )
        
        # Step 7: 龙头判定与决策
        if stock_info['is_leader']:
            confidence = self._calculate_confidence(market_state, stock_info, sector_effect, chip_quality_result, sector_money)

            return self._apply_market_gate({
                'decision': 'BUY',
                'code': code,
                'confidence': confidence,
                'reason': self._generate_buy_reason(market_state, stock_info, sector_effect, chip_quality_result, sector_money),
                'market_state': market_state,
                'stock_info': stock_info,
                'sector_effect': sector_effect,
                'sector_money': sector_money,
                'chip_quality': chip_quality_result,
                'arbitrage': []
            }, market_state)
        else:
            return self._ignore_result(
                code,
                f"⚠️ 非板块龙头，封单{stock_info['seal_amount']/100000000:.2f}亿不是最大",
                market_state,
                stock_info=stock_info,
                chip_quality=chip_quality_result,
                sector_effect=sector_effect,
                sector_money=sector_money,
                confidence=3
            )
    
    def batch_make_decision(self, codes: List[str]) -> Dict[str, Dict]:
        """
        批量决策优化（增强版）- 整合筹码质量分析
        """
        print(f"[增强批量决策] 开始处理 {len(codes)} 只股票...")
        
        # Step 1: 只获取一次全局数据
        zt_pool = self.data_fetcher.get_limit_up_pool()
        market_state = self.risk_engine.get_market_state(zt_pool=zt_pool)
        sector_money_map = self.data_fetcher.get_sector_money_flow_map()
        
        # 预处理涨停池，按板块分组
        sector_map = self._build_sector_map(zt_pool)
        
        # 预计算筹码质量（如果启用）
        chip_quality_results = {}
        if self.enable_chip_quality:
            print("[增强批量决策] 开始筹码质量分析...")
            chip_quality_results = self.chip_quality.batch_analyze(codes, days=30, pool_data=zt_pool)
            print("[增强批量决策] 筹码质量分析完成")
        
        results = {}
        
        for idx, code in enumerate(codes):
            try:
                # 使用预计算的筹码质量结果
                chip_quality = chip_quality_results.get(code) if self.enable_chip_quality else None
                
                # 使用共享的全局数据进行决策
                result = self._single_decision(
                    code, 
                    market_state, 
                    zt_pool, 
                    sector_map,
                    chip_quality,
                    sector_money_map
                )
                results[code] = result
                
                # 每10只打印进度
                if (idx + 1) % 10 == 0:
                    print(f"[增强批量决策] 已完成 {idx + 1}/{len(codes)}...")
                    
            except Exception as e:
                print(f"批量决策失败 {code}: {e}")
                results[code] = {
                    'decision': 'ERROR',
                    'code': code,
                    'confidence': 0,
                    'reason': f'决策错误: {str(e)}',
                    'market_state': {},
                    'stock_info': {},
                    'sector_effect': {},
                    'sector_money': {},
                    'chip_quality': {},
                    'arbitrage': []
                }
        
        print(f"[增强批量决策] 全部完成！")
        return results
    
    def _single_decision(
        self,
        code: str,
        market_state: Dict,
        zt_pool: List[Dict],
        sector_map: Dict[str, List[Dict]],
        chip_quality: Dict = None,
        sector_money_map: Dict[str, Dict] = None
    ) -> Dict:
        """
        单只股票决策（使用预获取的共享数据）
        """
        # 注：空仓态不再直接拦截，照常分析，结果经 _apply_market_gate 降级

        # 个股分析
        stock_info = self.stock_selector.analyze_stock(code, zt_pool=zt_pool)
        
        if 'error' in stock_info:
            return self._ignore_result(code,
                f"❌ 数据错误: {stock_info['error']}",
                market_state,
                stock_info=stock_info,
                confidence=5
            )
        
        # 涨停检查
        if not stock_info['is_limit_up']:
            return self._ignore_result(
                code,
                "⚠️ 股票未涨停，不符合龙头战法",
                market_state,
                stock_info=stock_info,
                confidence=3
            )
        
        # 筹码质量检查
        if self.enable_chip_quality and chip_quality:
            if not chip_quality['pass_risk_filter']:
                reasons = []
                filter_details = chip_quality['filter_details']
                
                if not filter_details.get('filter1_chip_dirty_pass', True):
                    reasons.append(filter_details['filter1_reason'])
                if not filter_details.get('filter2_yizi_burst_pass', True):
                    reasons.append(filter_details['filter2_reason'])
                
                return self._ignore_result(
                    code,
                    f"❌ 筹码质量风控: {'; '.join(reasons)}",
                    market_state,
                    stock_info=stock_info,
                    chip_quality=chip_quality,
                    confidence=4
                )
        
        # 可买性检查
        if not stock_info['is_buyable']:
            arbitrage = self.stock_selector.get_20cm_arbitrage(code)
            
            return self._ignore_result(
                code,
                f"⚠️ {stock_info['buyable_reason']}",
                market_state,
                stock_info=stock_info,
                chip_quality=chip_quality,
                arbitrage=arbitrage,
                arbitrage_tip='💡 建议：考虑以下20cm套利标的' if arbitrage else '',
                confidence=4
            )
        
        # 板块效应检查
        sector_effect = self.stock_selector.check_sector_effect_fast(stock_info, sector_map) if sector_map else self.stock_selector.check_sector_effect(stock_info)
        
        if not sector_effect['has_effect']:
            return self._ignore_result(
                code,
                f"⚠️ 板块效应不足: {sector_effect['sector_name']} 仅{sector_effect['limit_up_count']}只涨停（需≥3只）",
                market_state,
                stock_info=stock_info,
                chip_quality=chip_quality,
                sector_effect=sector_effect,
                confidence=3
            )

        sector_money = self.sector_money_analyzer.analyze_sector(
            sector_effect.get('sector_name', ''),
            zt_pool=zt_pool,
            money_flow_map=sector_money_map or {}
        )
        if self.sector_money_analyzer.should_block_entry(
            sector_money,
            sector_effect.get('limit_up_count', 0)
        ):
            return self._ignore_result(
                code,
                f"⚠️ 板块资金确认不足: {sector_money.get('reason', '')}",
                market_state,
                stock_info=stock_info,
                chip_quality=chip_quality,
                sector_effect=sector_effect,
                sector_money=sector_money,
                confidence=3
            )
        
        # 龙头判定
        is_leader = self.stock_selector.check_leader_fast(stock_info, zt_pool) if zt_pool else stock_info.get('is_leader', False)
        
        if is_leader:
            confidence = self._calculate_confidence(market_state, stock_info, sector_effect, chip_quality, sector_money)

            return self._apply_market_gate({
                'decision': 'BUY',
                'code': code,
                'confidence': confidence,
                'reason': self._generate_buy_reason(market_state, stock_info, sector_effect, chip_quality, sector_money),
                'market_state': market_state,
                'stock_info': stock_info,
                'sector_effect': sector_effect,
                'sector_money': sector_money,
                'chip_quality': chip_quality,
                'arbitrage': []
            }, market_state)
        else:
            return self._ignore_result(
                code,
                f"⚠️ 非板块龙头，封单{stock_info['seal_amount']/100000000:.2f}亿不是最大",
                market_state,
                stock_info=stock_info,
                chip_quality=chip_quality,
                sector_effect=sector_effect,
                sector_money=sector_money,
                confidence=3
            )
    
    def _calculate_confidence(
        self,
        market_state: Dict,
        stock_info: Dict,
        sector_effect: Dict,
        chip_quality: Dict = None,
        sector_money: Dict = None
    ) -> int:
        """
        计算买入信心指数 (1-5) - 增强版
        """
        score = 0
        sentiment = market_state.get('sentiment', {})
        board_type = stock_info.get('board_type', '')
        
        # 市场状态加分
        if market_state['state'] == '主升浪':
            score += 2
        elif market_state['state'] == '投机抱团':
            score += 2
        else:
            score += 1

        # 情绪温度加分
        if sentiment.get('temperature') == 'hot':
            score += 1
        elif sentiment.get('temperature') == 'warm':
            score += 1
        elif sentiment.get('temperature') == 'ice':
            score -= 1

        # 风格匹配加分
        style_bias = sentiment.get('style_bias', 'balanced')
        if style_bias == 'premium_smallcap':
            if board_type in ('gem', 'star'):
                score += 1
            elif board_type == 'main':
                score -= 1
        elif style_bias == 'main_board':
            if board_type == 'main':
                score += 1
            elif board_type in ('gem', 'star'):
                score -= 1
        
        # 封单金额加分
        seal_amount = stock_info['seal_amount']
        if seal_amount >= 30_0000_0000:  # 30亿+
            score += 2
        elif seal_amount >= 19_0000_0000:  # 19亿+
            score += 1
        
        # 连板加分
        if stock_info['limit_count'] >= 3:
            score += 1
        
        # 板块热度加分
        if sector_effect['limit_up_count'] >= 5:
            score += 1

        score += self.sector_money_analyzer.confidence_adjustment(sector_money)
        
        # 筹码质量加分（新增）
        if chip_quality:
            chip_score = chip_quality['total_score']
            if chip_score >= 20:
                score += 1  # 筹码质量优秀
            elif chip_score >= 10:
                score += 0  # 筹码质量一般
            else:
                score -= 1  # 筹码质量较差（不过过不了风控）
        
        return min(max(score, 1), 5)
    
    def _generate_buy_reason(
        self,
        market_state: Dict,
        stock_info: Dict,
        sector_effect: Dict,
        chip_quality: Dict = None,
        sector_money: Dict = None
    ) -> str:
        """生成买入理由（增强版）"""
        reasons = ["✅ 符合买入条件:"]
        sentiment = market_state.get('sentiment', {})
        
        # 市场环境
        reasons.append(f"📈 市场: {market_state['state']}")
        if sentiment:
            reasons.append(
                f"🌡️ 情绪: {self._temperature_label(sentiment.get('temperature'))}"
                f"（涨停{sentiment.get('total_limit_ups', 0)}家，高度{sentiment.get('max_limit_count', 0)}板）"
            )
            reasons.append(f"🧭 风格: {self._style_bias_label(sentiment.get('style_bias'))}")
            reasons.append(
                f"🎯 匹配: {self._describe_style_fit(stock_info.get('board_type', ''), sentiment)}"
            )
        
        # 龙头地位
        seal_yi = stock_info['seal_amount'] / 100000000
        reasons.append(f"👑 龙头: 封单{seal_yi:.2f}亿，{stock_info['limit_count']}连板")
        
        # 板块效应
        reasons.append(f"🔥 板块: {sector_effect['sector_name']} 共{sector_effect['limit_up_count']}只涨停")
        if sector_money:
            net_yi = sector_money.get('net_inflow', 0) / 100000000
            rank = sector_money.get('rank')
            rank_text = f"，排名第{rank}" if rank else ""
            reasons.append(
                f"💰 板块资金: {self._money_temperature_label(sector_money.get('money_temperature'))}"
                f"（净流入{net_yi:.2f}亿{rank_text}，{sector_money.get('reason', '')}）"
            )
        
        # 筹码质量（新增）
        if chip_quality:
            chip_score = chip_quality['total_score']
            reasons.append(f"🎲 筹码质量: 得分{chip_score}")
            
            # 添加得分详情
            score_details = chip_quality['score_details']
            if score_details['score1_limitup_quality'] != 0:
                reasons.append(f"   - {score_details['score1_reason']}")
            if score_details['score2_weak_to_strong'] != 0:
                reasons.append(f"   - {score_details['score2_reason']}")
            if score_details.get('score6_market_sentiment', 0) != 0:
                reasons.append(f"   - {score_details['score6_reason']}")
            if score_details.get('score7_board_style_fit', 0) != 0:
                reasons.append(f"   - {score_details['score7_reason']}")
        
        # 操作提示
        reasons.append(f"💰 建议: {market_state['suggestion']}")
        
        return "\n".join(reasons)

    @staticmethod
    def _build_sector_map(zt_pool: List[Dict]) -> Dict[str, List[Dict]]:
        """构建板块 -> 涨停股列表映射，供单股/批量路径复用。"""
        sector_map = {}
        for stock in zt_pool:
            sector = stock.get('sector', '其他')
            if sector not in sector_map:
                sector_map[sector] = []
            sector_map[sector].append(stock)
        return sector_map

    def _build_pool_context(
        self,
        code: str,
        stock_info: Dict,
        zt_pool: List[Dict],
        market_sentiment: Dict = None
    ) -> Dict:
        """构建筹码质量分析所需的共享上下文。"""
        clean_code = str(code).split('.')[0]
        pool_info = {}

        for stock in zt_pool:
            if stock.get('code') == clean_code:
                pool_info = dict(stock)
                break

        sector = stock_info.get('sector') or pool_info.get('sector', '')
        sector_zt_count = 0
        if sector:
            sector_zt_count = sum(1 for stock in zt_pool if stock.get('sector') == sector)

        pool_info.setdefault('code', clean_code)
        pool_info.setdefault('name', stock_info.get('name', ''))
        pool_info.setdefault('seal_amount', stock_info.get('seal_amount', 0))
        pool_info.setdefault('first_limit_time', stock_info.get('first_limit_time', ''))
        pool_info.setdefault('limit_count', stock_info.get('limit_count', 0))
        pool_info.setdefault('turnover_rate', stock_info.get('turnover_rate', 0))
        pool_info.setdefault('board_type', stock_info.get('board_type', ''))
        pool_info.setdefault('limit_up_threshold', stock_info.get('limit_up_threshold', 0))
        pool_info['sector_zt_count'] = sector_zt_count
        pool_info['market_sentiment'] = market_sentiment or {}
        return pool_info

    @staticmethod
    def _temperature_label(value: str) -> str:
        labels = {
            'hot': '火热',
            'warm': '回暖',
            'neutral': '中性',
            'ice': '冰点',
        }
        return labels.get(value, '未知')

    @staticmethod
    def _style_bias_label(value: str) -> str:
        labels = {
            'premium_smallcap': '创业板/科创板高弹性',
            'main_board': '主板连板',
            'balanced': '风格均衡',
        }
        return labels.get(value, '风格未知')

    def _describe_style_fit(self, board_type: str, sentiment: Dict) -> str:
        board_label = {
            'main': '主板',
            'gem': '创业板',
            'star': '科创板',
            'bse': '北交所',
        }.get(board_type, '未知板块')
        style_bias = sentiment.get('style_bias', 'balanced')

        if style_bias == 'premium_smallcap':
            if board_type in ('gem', 'star'):
                return f"当前偏20cm高弹性，{board_label}更容易获得溢价"
            return f"当前偏20cm高弹性，{board_label}弹性略弱"
        if style_bias == 'main_board':
            if board_type == 'main':
                return "当前偏主板连板，标的与风格一致"
            return f"当前偏主板连板，{board_label}需更强辨识度"
        return f"当前风格均衡，{board_label}中性"

    @staticmethod
    def _money_temperature_label(value: str) -> str:
        labels = {
            'hot': '资金强',
            'warm': '资金偏暖',
            'neutral': '资金中性',
            'cold': '资金偏冷',
            'unknown': '资金未知',
        }
        return labels.get(value, '资金未知')
    
    def _ignore_result(
        self,
        code: str,
        reason: str,
        market_state: Dict,
        stock_info: Dict = None,
        sector_effect: Dict = None,
        sector_money: Dict = None,
        chip_quality: Dict = None,
        arbitrage: List[Dict] = None,
        arbitrage_tip: str = '',
        confidence: int = 3
    ) -> Dict:
        """生成忽略结果"""
        result = {
            'decision': 'IGNORE',
            'code': code,
            'confidence': confidence,
            'reason': reason,
            'market_state': market_state,
            'stock_info': stock_info or {},
            'sector_effect': sector_effect or {},
            'sector_money': sector_money or {},
            'chip_quality': chip_quality or {},
            'arbitrage': arbitrage or [],
            'arbitrage_tip': arbitrage_tip
        }
        warning = self._market_risk_warning(market_state)
        if warning:
            result['risk_warning'] = warning
        return result

    @staticmethod
    def _market_risk_warning(market_state: Dict) -> str:
        """空仓态时生成风控警告文案，可交易时返回空串"""
        if not market_state or market_state.get('can_trade', True):
            return ''
        return f"⚠️ 风控警告: {market_state.get('state', '未知')} - {market_state.get('suggestion', '建议空仓观望')}"

    def _apply_market_gate(self, result: Dict, market_state: Dict) -> Dict:
        """
        市场风控降级（替代原"空仓态直接IGNORE"的硬拦截）：
        空仓态下个股分析照常完成，BUY 降级为 WATCH，confidence 压至 ≤2，并附加风控警告
        """
        warning = self._market_risk_warning(market_state)
        if not warning:
            return result
        result['risk_warning'] = warning
        if result.get('decision') == 'BUY':
            result['decision'] = 'WATCH'
            result['confidence'] = min(int(result.get('confidence', 1)), 2)
            result['reason'] = f"{warning}（仅观察，不建议买入）；{result.get('reason', '')}"
        return result
    
    def get_high_quality_candidates(
        self,
        codes: List[str],
        min_chip_score: int = 10
    ) -> List[Dict]:
        """
        获取高质量候选标的（整合理念）
        
        Args:
            codes: 候选股票代码
            min_chip_score: 最低筹码质量得分
        
        Returns:
            list: 符合条件的高质量候选（按得分降序）
        """
        if not self.enable_chip_quality:
            print("[警告] 筹码质量分析未启用，返回空列表")
            return []
        
        # 获取高质量股票
        high_quality = self.chip_quality.get_high_quality_stocks(
            codes,
            min_score=min_chip_score,
            days=30
        )
        
        # 对每个高质量股票进行完整决策
        results = []
        
        print(f"[高质量候选] 对{len(high_quality)}只股票进行完整决策...")
        
        for stock in high_quality:
            code = stock['code']
            
            # 完整决策
            decision = self.make_decision(code)
            
            if decision['decision'] == 'BUY':
                results.append({
                    'code': code,
                    'name': stock['name'],
                    'chip_score': stock['score'],
                    'decision_confidence': decision['confidence'],
                    'reason': decision['reason'],
                    'full_decision': decision
                })
        
        # 按筹码质量和决策信心综合排序
        results.sort(
            key=lambda x: (x['chip_score'] + x['decision_confidence']),
            reverse=True
        )
        
        return results


# 测试代码
if __name__ == "__main__":
    print("=== 增强版决策引擎测试 ===\n")
    
    # 初始化（启用筹码质量分析）
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
    
    if zt_pool:
        test_code = zt_pool[0]['code']
        print(f"测试股票: {test_code} {zt_pool[0]['name']}\n")
        
        result = decision_maker.make_decision(test_code)
        
        print(f"{'='*60}")
        print(f"决策结果: {result['decision']}")
        print(f"信心指数: {'⭐' * result['confidence']} ({result['confidence']}/5)")
        print(f"\n{result['reason']}")
        print(f"{'='*60}")
        
        # 显示筹码质量（如果有）
        if result.get('chip_quality'):
            cq = result['chip_quality']
            print(f"\n🎲 筹码质量分析:")
            print(f"   通过风控: {'✅' if cq['pass_risk_filter'] else '❌'}")
            print(f"   总得分: {cq['total_score']}")
            print(f"   推荐: {cq['recommendation']}")
        
        # 显示套利推荐（如果有）
        if result.get('arbitrage'):
            print(f"\n💡 20cm套利推荐:")
            for arb in result['arbitrage'][:3]:
                print(f"  {arb['code']} {arb['name']} ({arb['board_type']})")
        
        print(f"\n{'='*60}")
        print("=== 高质量候选推荐 ===")
        
        # 获取高质量候选
        test_codes = [s['code'] for s in zt_pool[:10]]  # 测试前10只
        candidates = decision_maker.get_high_quality_candidates(test_codes, min_chip_score=10)
        
        if candidates:
            print(f"找到 {len(candidates)} 只高质量候选:\n")
            for candidate in candidates[:5]:
                print(f"{'─'*50}")
                print(f"{candidate['code']} {candidate['name']}")
                print(f"筹码得分: {candidate['chip_score']} | 决策信心: {candidate['decision_confidence']}")
                print(f"理由: {candidate['reason']}")
        else:
            print("未找到符合条件的候选")
    else:
        print("今日无涨停股，使用模拟数据测试市场状态...")
        market_state = decision_maker.risk_engine.get_market_state()
        print(f"市场状态: {market_state['state']}")
        print(f"可否交易: {market_state['can_trade']}")
        print(f"操作建议: {market_state['suggestion']}")
