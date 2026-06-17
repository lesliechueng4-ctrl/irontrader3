"""
基本面质量评分模块 (维度⑤)
评估个股基本面：盈利能力/估值水平/机构评级
为低吸提供"安全垫"判断
"""

import pandas as pd
import requests
from datetime import datetime
from typing import Dict, Optional
from data_fetcher import DataFetcher
import akshare as ak


class FundamentalScorer:
    """基本面质量评分器"""

    CACHE_VERSION = 5

    def __init__(self, data_fetcher: DataFetcher):
        self.fetcher = data_fetcher

    def score(self, stock_code: str) -> dict:
        """
        评估个股基本面质量
        
        Args:
            stock_code: 股票代码
        
        Returns:
            {
                'score': 0-100,
                'earnings': {
                    'revenue_growth': float,
                    'profit_growth': float,
                    'gross_margin': float,
                    'net_margin': float,
                    'roe': float,
                },
                'valuation': {
                    'pe_ttm': float,
                    'pb': float,
                    'total_mv': float,   # 总市值(亿)
                },
                'institution': {
                    'rating_count': int,
                    'buy_count': int,
                    'target_price': float,
                    'current_vs_target': str,
                },
                'quality_label': str,  # '优质'|'良好'|'一般'|'较差'|'数据不足'
            }
        """
        clean_code = self.fetcher._normalize_code(stock_code)

        # 增加缓存机制：基本面数据变化极慢，缓存24小时 (86400秒)
        cache_key = f"fundamental_score_v{self.CACHE_VERSION}_{clean_code}"
        cached = self.fetcher._get_cache(cache_key)
        if cached is not None:
            if self._is_cache_usable(cached):
                return cached
            self._delete_cache(cache_key)

        # 获取各项基本面数据
        stock_info = self._get_stock_info(clean_code)
        stock_info = self._fill_missing_valuation_from_cache(clean_code, stock_info)
        financial = self._get_financial_data(clean_code)
        institution = self._get_institution_rating(clean_code)

        # 合并估值数据
        valuation = {
            'pe_ttm': stock_info.get('pe_ttm', 0),
            'pb': stock_info.get('pb', 0),
            'total_mv': stock_info.get('total_mv', 0),
        }

        # 合并盈利数据
        earnings = {
            'revenue_growth': financial.get('revenue_growth', 0),
            'profit_growth': financial.get('profit_growth', 0),
            'gross_margin': financial.get('gross_margin', 0),
            'net_margin': financial.get('net_margin', 0),
            'roe': financial.get('roe', 0),
        }

        # 获取当前价格（用于对比目标价）
        realtime = self.fetcher.get_stock_realtime(clean_code)
        current_price = realtime.get('current', 0)
        target_price = institution.get('target_price', 0)
        
        if target_price > 0 and current_price > 0:
            if current_price < target_price * 0.8:
                current_vs_target = '低于目标'
            elif current_price > target_price * 1.1:
                current_vs_target = '高于目标'
            else:
                current_vs_target = '接近目标'
        else:
            current_vs_target = '无数据'

        institution_result = {
            'rating_count': institution.get('rating_count', 0),
            'buy_count': institution.get('buy_count', 0),
            'target_price': target_price,
            'current_vs_target': current_vs_target,
        }

        # 判断数据完整性
        has_earnings = any(v != 0 for v in earnings.values())
        has_valuation = valuation['pe_ttm'] != 0

        # 计算综合得分
        score = self._calculate_score(earnings, valuation, institution_result, 
                                       has_earnings, has_valuation)

        # 确定质量标签
        if not has_earnings and not has_valuation:
            quality_label = '数据不足'
        elif score >= 75:
            quality_label = '优质'
        elif score >= 55:
            quality_label = '良好'
        elif score >= 35:
            quality_label = '一般'
        else:
            quality_label = '较差'

        result = {
            'cache_version': self.CACHE_VERSION,
            'score': score,
            'earnings': earnings,
            'valuation': valuation,
            'institution': institution_result,
            'quality_label': quality_label,
        }
        
        if self._is_cache_usable(result):
            self.fetcher._set_cache(cache_key, result)
        return result

    def _is_cache_usable(self, result: dict) -> bool:
        """Avoid pinning transient upstream failures as a 24-hour result."""
        if not isinstance(result, dict):
            return False
        if result.get('cache_version') != self.CACHE_VERSION:
            return False

        valuation = result.get('valuation') or {}
        earnings = result.get('earnings') or {}

        return self._has_complete_valuation(valuation)

    def _delete_cache(self, cache_key: str):
        cache_manager = getattr(self.fetcher, 'cache_manager', None)
        if cache_manager and hasattr(cache_manager, 'delete'):
            cache_manager.delete(cache_key)

    def _fill_missing_valuation_from_cache(self, code: str, stock_info: dict) -> dict:
        """Reuse last good valuation when the quote API only returns partial data."""
        if stock_info.get('pe_ttm') and stock_info.get('pb') and stock_info.get('total_mv'):
            return stock_info

        cache_manager = getattr(self.fetcher, 'cache_manager', None)
        if not cache_manager or not hasattr(cache_manager, 'get'):
            return stock_info

        fallback_keys = [
            f"fundamental_score_v4_{code}",
            f"fundamental_score_v3_{code}",
            f"fundamental_score_v2_{code}",
            f"fundamental_score_{code}",
        ]
        for key in fallback_keys:
            cached = cache_manager.get(key)
            valuation = (cached or {}).get('valuation') or {}
            if not valuation:
                continue

            if not stock_info.get('pe_ttm') and valuation.get('pe_ttm'):
                stock_info['pe_ttm'] = valuation.get('pe_ttm')
            if not stock_info.get('pb') and valuation.get('pb'):
                stock_info['pb'] = valuation.get('pb')
            if not stock_info.get('total_mv') and valuation.get('total_mv'):
                stock_info['total_mv'] = valuation.get('total_mv')

            if stock_info.get('pe_ttm') and stock_info.get('pb') and stock_info.get('total_mv'):
                break

        return stock_info

    def _has_complete_valuation(self, valuation: dict) -> bool:
        return all(
            valuation.get(key, 0) not in (0, None, '', '-')
            for key in ('pe_ttm', 'pb', 'total_mv')
        )

    def _get_stock_info(self, code: str) -> dict:
        """获取个股基本信息（PE/PB/市值等）"""
        result = {'pe_ttm': 0, 'pb': 0, 'total_mv': 0, 'sector': ''}

        # 方法1: 东方财富直接API
        try:
            if code.startswith('6'):
                secid = f"1.{code}"
            else:
                secid = f"0.{code}"

            url = "http://push2.eastmoney.com/api/qt/stock/get"
            params = {
                'secid': secid,
                'fields': 'f57,f58,f162,f167,f164,f163,f173,f168,f116,f117',
                'ut': 'b2884a393a59ad64002292a3e90d46a5',
            }
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Referer': 'http://quote.eastmoney.com'
            }

            resp = requests.get(url, params=params, headers=headers, 
                              timeout=10, proxies={'http': None, 'https': None})
            
            if resp.status_code == 200:
                data = resp.json().get('data', {})
                if data:
                    pe = data.get('f162', 0)  # 市盈率
                    pb = data.get('f167', 0)  # 市净率
                    total_mv = data.get('f116', 0)  # 总市值

                    result['pe_ttm'] = float(pe) / 100 if pe and pe != '-' else 0
                    result['pb'] = float(pb) / 100 if pb and pb != '-' else 0
                    result['total_mv'] = float(total_mv) / 100_000_000 if total_mv else 0

                    if self._has_complete_valuation(result):
                        return result
        except Exception as e:
            print(f"东方财富获取 {code} 信息失败: {e}")

        # 方法2: akshare
        try:
            df = ak.stock_individual_info_em(symbol=code)
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    item = str(row.iloc[0]) if len(row) > 0 else ''
                    value = row.iloc[1] if len(row) > 1 else ''
                    
                    if '总市值' in item:
                        result['total_mv'] = self._parse_value(value) / 100_000_000
                    elif '市盈率' in item:
                        result['pe_ttm'] = self._parse_value(value)
                    elif '市净率' in item:
                        result['pb'] = self._parse_value(value)
                    elif '行业' in item:
                        result['sector'] = str(value)
                if self._has_complete_valuation(result):
                    return result
        except Exception as e:
            print(f"akshare 获取 {code} 信息失败: {e}")

        tencent_info = self._get_tencent_stock_info(code)
        for key, value in tencent_info.items():
            if key == 'sector':
                if value and not result.get(key):
                    result[key] = value
            elif value and not result.get(key):
                result[key] = value

        return result

    def _get_tencent_stock_info(self, code: str) -> dict:
        """Tencent quote fallback for PE/PB/market cap when Eastmoney is unstable."""
        result = {'pe_ttm': 0, 'pb': 0, 'total_mv': 0}

        try:
            market = 'sh' if code.startswith(('6', '9')) else 'sz'
            url = f"http://qt.gtimg.cn/q={market}{code}"
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Referer': 'http://gu.qq.com',
            }
            resp = requests.get(url, headers=headers, timeout=8,
                                proxies={'http': None, 'https': None})
            if resp.status_code != 200 or '="' not in resp.text:
                return result

            text = resp.content.decode('gbk', errors='ignore')
            data_str = text.split('="', 1)[1].split('"', 1)[0]
            parts = data_str.split('~')

            result['pe_ttm'] = self._parse_value(parts[39]) if len(parts) > 39 else 0
            result['total_mv'] = self._parse_value(parts[45]) if len(parts) > 45 else 0
            result['pb'] = self._parse_value(parts[46]) if len(parts) > 46 else 0
        except Exception as e:
            print(f"腾讯获取 {code} 估值失败: {e}")

        return result

    def _get_financial_data(self, code: str) -> dict:
        """获取财务数据"""
        result = {
            'revenue_growth': 0,
            'profit_growth': 0,
            'gross_margin': 0,
            'net_margin': 0,
            'roe': 0,
        }

        # 方法1: 东方财富API获取核心财务指标
        try:
            if code.startswith('6'):
                secid = f"1.{code}"
            else:
                secid = f"0.{code}"

            url = "http://push2.eastmoney.com/api/qt/stock/get"
            params = {
                'secid': secid,
                'fields': 'f164,f173,f183,f184,f185,f186,f187,f188,f190',
                'ut': 'b2884a393a59ad64002292a3e90d46a5',
            }
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Referer': 'http://quote.eastmoney.com'
            }

            resp = requests.get(url, params=params, headers=headers, 
                              timeout=10, proxies={'http': None, 'https': None})
            
            if resp.status_code == 200:
                data = resp.json().get('data', {})
                if data:
                    # f173 = 毛利率, f164 = ROE
                    # f185 = 营收增长, f186 = 净利增长, f187 = 净利率
                    roe = data.get('f164', 0)
                    gross_margin = data.get('f173', 0)
                    revenue_growth = data.get('f185', 0)
                    profit_growth = data.get('f186', 0)
                    net_margin = data.get('f187', 0)

                    result['roe'] = float(roe) / 100 if roe and roe != '-' else 0
                    result['gross_margin'] = float(gross_margin) / 100 if gross_margin and gross_margin != '-' else 0
                    result['revenue_growth'] = float(revenue_growth) / 100 if revenue_growth and revenue_growth != '-' else 0
                    result['profit_growth'] = float(profit_growth) / 100 if profit_growth and profit_growth != '-' else 0
                    result['net_margin'] = float(net_margin) / 100 if net_margin and net_margin != '-' else 0
        except Exception as e:
            print(f"东方财富获取 {code} 财务数据失败: {e}")

        # 方法2: akshare 财务摘要
        try:
            df = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
            if df is not None and not df.empty:
                latest = self._latest_financial_row(df)
                for col in df.columns:
                    col_str = str(col)
                    if '营业总收入同比' in col_str or '营收增长' in col_str:
                        result['revenue_growth'] = self._parse_value(latest.get(col, 0))
                    elif '净利润同比' in col_str or '归母净利润同比' in col_str:
                        result['profit_growth'] = self._parse_value(latest.get(col, 0))
                    elif '毛利率' in col_str:
                        result['gross_margin'] = self._parse_value(latest.get(col, 0))
                    elif '净利率' in col_str:
                        result['net_margin'] = self._parse_value(latest.get(col, 0))
                    elif 'ROE' in col_str.upper() or '净资产收益率' in col_str:
                        result['roe'] = self._parse_value(latest.get(col, 0))
                return result
        except Exception as e:
            print(f"akshare 获取 {code} 财务数据失败: {e}")

        return result

    def _latest_financial_row(self, df: pd.DataFrame) -> pd.Series:
        """THS data is ascending by report period in some AKShare versions."""
        if '报告期' not in df.columns:
            return df.iloc[-1]

        sorted_df = df.copy()
        sorted_df['_report_period_sort'] = pd.to_numeric(sorted_df['报告期'], errors='coerce')
        sorted_df = sorted_df.sort_values('_report_period_sort')
        return sorted_df.drop(columns=['_report_period_sort']).iloc[-1]

    def _get_institution_rating(self, code: str) -> dict:
        """获取机构评级数据"""
        result = {
            'rating_count': 0,
            'buy_count': 0,
            'target_price': 0,
        }

        try:
            df = ak.stock_comment_detail_zlkp_jgcyd_em(symbol=code)
            if df is not None and not df.empty:
                # 解析评级数据
                total = len(df)
                buy_count = 0
                target_prices = []
                
                for _, row in df.iterrows():
                    rating = str(row.get('评级', row.get('投资评级', '')))
                    if '买入' in rating or '增持' in rating or '推荐' in rating:
                        buy_count += 1
                    
                    # 目标价
                    target = row.get('目标价', row.get('预测目标价', 0))
                    if target and pd.notna(target):
                        try:
                            tp = float(target)
                            if tp > 0:
                                target_prices.append(tp)
                        except (ValueError, TypeError):
                            pass

                result['rating_count'] = total
                result['buy_count'] = buy_count
                result['target_price'] = sum(target_prices) / len(target_prices) if target_prices else 0

        except Exception as e:
            print(f"获取 {code} 机构评级失败: {e}")

        return result

    def _parse_value(self, value) -> float:
        """解析各种格式的数值"""
        try:
            if value is None or pd.isna(value):
                return 0
            text = str(value).replace(',', '').replace('%', '').strip()
            if not text or text in ('-', '--', 'nan', 'None', ''):
                return 0
            
            multiplier = 1.0
            if text.endswith('亿'):
                multiplier = 100_000_000
                text = text[:-1]
            elif text.endswith('万'):
                multiplier = 10_000
                text = text[:-1]
            
            return float(text) * multiplier
        except (ValueError, TypeError):
            return 0

    def _calculate_score(self, earnings: dict, valuation: dict, 
                          institution: dict, has_earnings: bool, 
                          has_valuation: bool) -> int:
        """计算基本面综合得分 (0-100)"""
        
        if not has_earnings and not has_valuation:
            return 50  # 数据不足给中间分

        score = 0

        # === 1. 盈利能力 (40分) ===
        # 营收增速 (15分)
        rev = earnings.get('revenue_growth', 0)
        if rev > 30:
            score += 15
        elif rev > 10:
            score += 10
        elif rev > 0:
            score += 5
        # 负增长不加分

        # 净利润增速 (15分)
        profit = earnings.get('profit_growth', 0)
        if profit > 50:
            score += 15
        elif profit > 15:
            score += 10
        elif profit > 0:
            score += 5
        # 负增长不加分

        # ROE (10分)
        roe = earnings.get('roe', 0)
        if roe > 15:
            score += 10
        elif roe > 8:
            score += 7
        elif roe > 3:
            score += 3

        # === 2. 估值水平 (30分) ===
        pe = valuation.get('pe_ttm', 0)
        if pe > 0:
            if pe < 30:
                score += 15
            elif pe < 60:
                score += 10
            elif pe < 100:
                score += 5
            # PE > 100 不加分
        elif pe < 0:
            # 亏损
            score += 0

        pb = valuation.get('pb', 0)
        if pb > 0:
            if pb < 3:
                score += 10
            elif pb < 6:
                score += 7
            elif pb < 10:
                score += 3

        # 目标价对比
        if institution.get('target_price', 0) > 0:
            cvt = institution.get('current_vs_target', '无数据')
            if cvt == '低于目标':
                score += 5

        # === 3. 机构评级 (15分) ===
        rating_count = institution.get('rating_count', 0)
        buy_count = institution.get('buy_count', 0)
        
        if rating_count > 0:
            buy_ratio = buy_count / rating_count
            if buy_ratio > 0.8:
                score += 15
            elif buy_ratio > 0.5:
                score += 10
            elif buy_ratio > 0:
                score += 5
        else:
            score += 5  # 无评级数据给基础分

        # === 4. 质量底线 (15分) ===
        gross = earnings.get('gross_margin', 0)
        if gross > 30:
            score += 8
        elif gross > 15:
            score += 5
        else:
            score += 2

        net = earnings.get('net_margin', 0)
        if net > 15:
            score += 7
        elif net > 5:
            score += 5
        else:
            score += 2

        return max(0, min(100, score))


# ========== 测试代码 ==========
if __name__ == "__main__":
    print("=" * 60)
    print("基本面质量评分测试")
    print("=" * 60)

    fetcher = DataFetcher()
    scorer = FundamentalScorer(fetcher)

    test_codes = ['603083', '002706']
    for code in test_codes:
        print(f"\n--- 测试 {code} ---")
        result = scorer.score(code)
        print(f"  得分: {result['score']}")
        print(f"  标签: {result['quality_label']}")
        
        e = result['earnings']
        print(f"  营收增速: {e['revenue_growth']:.1f}%")
        print(f"  净利增速: {e['profit_growth']:.1f}%")
        print(f"  毛利率: {e['gross_margin']:.1f}%")
        print(f"  净利率: {e['net_margin']:.1f}%")
        print(f"  ROE: {e['roe']:.1f}%")
        
        v = result['valuation']
        print(f"  PE(TTM): {v['pe_ttm']:.1f}")
        print(f"  PB: {v['pb']:.1f}")
        print(f"  总市值: {v['total_mv']:.1f}亿")

        i = result['institution']
        print(f"  机构评级: {i['buy_count']}/{i['rating_count']} 买入")
        print(f"  目标价: {i['target_price']:.1f}")
        print(f"  vs目标: {i['current_vs_target']}")
