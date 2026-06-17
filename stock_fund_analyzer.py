"""
个股资金动态分析模块 (维度③)
分析个股的资金博弈结构：主力/机构/北向/游资/融资
判断"谁在买、谁在卖"
"""

import pandas as pd
import time
from datetime import datetime, timedelta
from typing import Dict, Optional
from data_fetcher import DataFetcher
import akshare as ak


class StockFundAnalyzer:
    """个股资金动态分析器"""

    def __init__(self, data_fetcher: DataFetcher):
        self.fetcher = data_fetcher

    @staticmethod
    def _empty_fund_flow() -> dict:
        """Return an explicit "missing data" fund-flow payload."""
        return {
            'main_net_inflow_today': 0,
            'main_net_inflow_5day': 0,
            'main_net_inflow_trend': '数据不足',
            'super_large_net': 0,
            'large_net': 0,
            'has_data': False,
            'today_has_data': False,
            'five_day_has_data': False,
            'available_days': 0,
            'source': '',
            'as_of_date': '',
        }

    @staticmethod
    def _to_float(value) -> Optional[float]:
        """Parse numeric values that may include Chinese units."""
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except TypeError:
            pass

        text = str(value).replace(',', '').strip()
        if text in ('', '-', '--', 'None', 'nan'):
            return None

        multiplier = 1
        if text.endswith('亿'):
            multiplier = 100_000_000
            text = text[:-1]
        elif text.endswith('万'):
            multiplier = 10_000
            text = text[:-1]
        if text.endswith('%'):
            text = text[:-1]

        try:
            return float(text) * multiplier
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _find_col(df: pd.DataFrame, includes: tuple, excludes: tuple = ()) -> Optional[str]:
        for col in df.columns:
            name = str(col)
            if all(part in name for part in includes) and not any(part in name for part in excludes):
                return col
        return None

    def analyze(self, stock_code: str) -> dict:
        """
        分析个股资金博弈结构
        
        Args:
            stock_code: 股票代码
        
        Returns:
            {
                'score': 0-100,
                'fund_flow': {
                    'main_net_inflow_today': float,  # 今日主力净流入(元)
                    'main_net_inflow_5day': float,   # 5日主力累计净流入
                    'main_net_inflow_trend': str,    # '持续流入'|'持续流出'|'转入'|'转出'|'震荡'
                    'super_large_net': float,        # 超大单净流入
                    'large_net': float,              # 大单净流入
                },
                'dragon_tiger': {
                    'institution_net': float,
                    'northbound_net': float,
                    'hot_money_net': float,
                    'has_data': bool,
                },
                'margin': {
                    'margin_balance': float,
                    'margin_balance_change': float,
                    'has_data': bool,
                },
                'signal': str,  # '强势共识'|'分歧博弈'|'游资主导'|'多方撤退'|'散户接盘'|'数据不足'
            }
        """
        clean_code = self.fetcher._normalize_code(stock_code)

        # 获取主力资金流向
        fund_flow = self._get_fund_flow(clean_code)

        # 获取龙虎榜数据
        dragon_tiger = self._get_dragon_tiger(clean_code)

        # 获取融资融券数据
        margin = self._get_margin_data(clean_code)

        # 判断资金信号
        signal = self._determine_signal(fund_flow, dragon_tiger, margin)

        # 计算综合得分
        score = self._calculate_score(fund_flow, dragon_tiger, margin, signal)

        return {
            'score': score,
            'fund_flow': fund_flow,
            'dragon_tiger': dragon_tiger,
            'margin': margin,
            'signal': signal,
        }

    def _get_fund_flow(self, code: str) -> dict:
        """获取个股主力资金流向"""
        default = self._empty_fund_flow()

        # 方法1: 东方财富直接API (更可靠)
        result = self._fetch_fund_flow_eastmoney(code)
        if result and result.get('five_day_has_data'):
            return result

        # 方法2: 新浪资金流独立兜底，避免 AKShare 和东财同源一起失效
        sina_result = self._fetch_fund_flow_sina(code)
        if sina_result and sina_result.get('has_data'):
            if result:
                result = self._merge_fund_flow(result, sina_result)
                if result.get('five_day_has_data'):
                    return result
            else:
                return sina_result

        # 方法3: 尝试 akshare
        try:
            market = "sh" if code.startswith("6") else "sz"
            df = ak.stock_individual_fund_flow(stock=code, market=market)
            if df is not None and not df.empty:
                ak_result = self._parse_akshare_fund_flow(df)
                if ak_result.get('has_data'):
                    if result:
                        return self._merge_fund_flow(result, ak_result)
                    return ak_result
        except Exception as e:
            print(f"akshare 获取 {code} 资金流向失败: {e}")

        if result:
            return result

        if sina_result:
            return sina_result

        return default

    def _fetch_fund_flow_eastmoney(self, code: str) -> Optional[dict]:
        """从东方财富API获取个股资金流向"""
        try:
            # 确定市场ID
            if code.startswith('6'):
                secid = f"1.{code}"
            elif code.startswith(('0', '3')):
                secid = f"0.{code}"
            else:
                secid = f"0.{code}"

            params = {
                'secid': secid,
                'fields1': 'f1,f2,f3,f7',
                'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65',
                'klt': 101,
                'lmt': 10,  # 最近10天
                'ut': 'b2884a393a59ad64002292a3e90d46a5',
            }
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': f'https://quote.eastmoney.com/{"sh" if secid.startswith("1.") else "sz"}{code}.html',
            }
            cache_key = f"stock_fund_flow_history_{code}"

            history_url = "http://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
            realtime_url = "http://push2.eastmoney.com/api/qt/stock/fflow/kline/get"

            history_flows = self._fetch_eastmoney_klines(
                history_url,
                params,
                headers,
                timeout=5,
                retries=4,
                source_name="eastmoney_fund_flow_history",
            )
            if history_flows:
                self.fetcher._set_cache(cache_key, history_flows)
                history_source = 'eastmoney'
            else:
                history_flows = self.fetcher._get_cache(cache_key) or []
                history_source = 'eastmoney_cache'

            realtime_flows = self._fetch_eastmoney_klines(
                realtime_url,
                params,
                headers,
                timeout=5,
                retries=2,
                source_name="eastmoney_fund_flow_realtime",
            )

            if history_flows:
                merged_flows = self._merge_daily_flows(history_flows, realtime_flows)
                return self._build_fund_flow_result(merged_flows, history_source)

            if realtime_flows:
                return self._build_fund_flow_result(realtime_flows, 'eastmoney_realtime')

        except Exception as e:
            print(f"东方财富API获取 {code} 资金流向失败: {e}")
        return None

    def _fetch_fund_flow_sina(self, code: str) -> Optional[dict]:
        """从新浪资金流接口获取最近交易日个股资金流向。"""
        try:
            symbol = self.fetcher._format_legacy_symbol(code)
            if not symbol.startswith(('sh', 'sz')):
                return None

            cache_key = f"stock_fund_flow_sina_{code}"
            url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_qsfx_lscjfb"
            params = {
                'daima': symbol,
                'page': 1,
                'num': 10,
                'sort': 'opendate',
                'asc': 0,
            }
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://finance.sina.com.cn/',
            }

            result = self.fetcher.source_client.get(
                "sina_fund_flow",
                url,
                params=params,
                headers=headers,
                timeout=6,
                retries=2,
            )
            if result.ok:
                rows = result.response.json()
                flows = self._parse_sina_fund_rows(rows)
                if flows:
                    self.fetcher._set_cache(cache_key, flows)
                    return self._build_fund_flow_result(flows, 'sina')
                print(f"新浪资金流接口无有效数据 {code}")
            else:
                print(f"新浪资金流接口失败 {code}: {result.error}")

            cached_flows = self.fetcher._get_cache(cache_key) or []
            if cached_flows:
                return self._build_fund_flow_result(cached_flows, 'sina_cache')
        except Exception as e:
            print(f"新浪资金流获取 {code} 失败: {e}")
        return None

    def _fetch_eastmoney_klines(
        self,
        url: str,
        params: dict,
        headers: dict,
        timeout: int,
        retries: int = 1,
        source_name: str = "eastmoney_fund_flow",
    ) -> list:
        request_params = dict(params)
        request_params['_'] = int(time.time() * 1000)
        result = self.fetcher.source_client.get(
            source_name,
            url,
            params=request_params,
            headers=headers,
            timeout=timeout,
            retries=retries,
        )
        if not result.ok:
            print(f"东方财富资金流接口失败 {url}: {result.error}")
            return []

        try:
            data = result.response.json()
            klines = (data.get('data') or {}).get('klines', [])
            flows = self._parse_eastmoney_klines(klines)
            if flows:
                return flows
            print(f"东方财富资金流接口无有效 klines {url}")
        except Exception as e:
            print(f"东方财富资金流解析失败 {url}: {e}")
        return []

    def _parse_eastmoney_klines(self, klines: list) -> list:
        """解析东方财富资金流 kline。"""
        daily_flows = []
        for line in klines or []:
            parts = str(line).split(',')
            if len(parts) < 6:
                continue

            main_net = self._to_float(parts[1])
            small_net = self._to_float(parts[2])
            medium_net = self._to_float(parts[3])
            large_net = self._to_float(parts[4])
            super_large_net = self._to_float(parts[5])
            if main_net is None:
                continue

            daily_flows.append({
                'date': parts[0],
                'main_net': main_net,
                'small_net': small_net or 0,
                'medium_net': medium_net or 0,
                'large_net': large_net or 0,
                'super_large_net': super_large_net or 0,
            })

        return sorted(daily_flows, key=lambda item: item['date'])

    def _parse_sina_fund_rows(self, rows: list) -> list:
        """解析新浪资金流行数据，主力口径优先使用超大单+大单。"""
        daily_flows = []
        if not isinstance(rows, list):
            return daily_flows

        for row in rows:
            if not isinstance(row, dict):
                continue

            date = str(row.get('opendate') or '').strip()
            if not date:
                continue

            super_large_net = self._to_float(row.get('r0_net'))
            large_net = self._to_float(row.get('r1_net'))
            fallback_net = self._to_float(row.get('netamount'))

            if super_large_net is not None or large_net is not None:
                main_net = (super_large_net or 0) + (large_net or 0)
            else:
                main_net = fallback_net

            if main_net is None:
                continue

            daily_flows.append({
                'date': date,
                'main_net': main_net,
                'large_net': large_net or 0,
                'super_large_net': super_large_net or 0,
            })

        return sorted(daily_flows, key=lambda item: item['date'])

    def _merge_daily_flows(self, primary: list, secondary: list) -> list:
        by_date = {item['date']: item for item in primary or [] if item.get('date')}
        for item in secondary or []:
            if item.get('date'):
                by_date[item['date']] = item
        return sorted(by_date.values(), key=lambda item: item['date'])

    def _build_fund_flow_result(self, daily_flows: list, source: str) -> Optional[dict]:
        if not daily_flows:
            return None

        daily_flows = sorted(daily_flows, key=lambda item: item['date'])
        today_flow = daily_flows[-1]
        has_five_day = len(daily_flows) >= 5
        recent_5 = daily_flows[-5:]

        return {
            'main_net_inflow_today': today_flow['main_net'],
            'main_net_inflow_5day': sum(d['main_net'] for d in recent_5) if has_five_day else 0,
            'main_net_inflow_trend': self._judge_fund_trend(daily_flows),
            'super_large_net': today_flow.get('super_large_net', 0),
            'large_net': today_flow.get('large_net', 0),
            'has_data': True,
            'today_has_data': True,
            'five_day_has_data': has_five_day,
            'available_days': len(daily_flows),
            'source': source,
            'as_of_date': today_flow.get('date', ''),
        }

    def _merge_fund_flow(self, primary: dict, secondary: dict) -> dict:
        merged = dict(primary)
        if not merged.get('today_has_data') and secondary.get('today_has_data'):
            for key in ('main_net_inflow_today', 'super_large_net', 'large_net', 'as_of_date'):
                merged[key] = secondary.get(key, merged.get(key, 0))
            merged['today_has_data'] = True

        if not merged.get('five_day_has_data') and secondary.get('five_day_has_data'):
            merged['main_net_inflow_5day'] = secondary.get('main_net_inflow_5day', 0)
            merged['main_net_inflow_trend'] = secondary.get('main_net_inflow_trend', '数据不足')
            merged['five_day_has_data'] = True

        merged['has_data'] = bool(merged.get('today_has_data') or merged.get('five_day_has_data'))
        merged['available_days'] = max(merged.get('available_days', 0), secondary.get('available_days', 0))
        if secondary.get('as_of_date', '') > merged.get('as_of_date', ''):
            merged['as_of_date'] = secondary.get('as_of_date', '')
        sources = [s for s in (merged.get('source'), secondary.get('source')) if s]
        merged['source'] = '+'.join(dict.fromkeys(sources))
        return merged

    def _parse_akshare_fund_flow(self, df: pd.DataFrame) -> dict:
        """解析 akshare 资金流向数据"""
        try:
            # 查找主力净流入列
            net_col = self._find_col(df, ('主力净流入', '净额')) or self._find_col(df, ('主力净流入',))

            if not net_col:
                return self._empty_fund_flow()

            values = df[net_col].map(self._to_float).dropna()
            if values.empty:
                return self._empty_fund_flow()

            super_col = self._find_col(df, ('超大单净流入', '净额')) or self._find_col(df, ('超大单', '净额'))
            large_col = self._find_col(df, ('大单净流入', '净额'), excludes=('超大单',)) or self._find_col(df, ('大单', '净额'), excludes=('超大单',))
            super_values = df[super_col].map(self._to_float).dropna() if super_col else pd.Series(dtype=float)
            large_values = df[large_col].map(self._to_float).dropna() if large_col else pd.Series(dtype=float)

            date_col = self._find_col(df, ('日期',)) or self._find_col(df, ('date',))
            daily_flows = []
            for i, v in values.items():
                if date_col and i in df.index:
                    flow_date = str(df.loc[i, date_col])
                else:
                    flow_date = str(i)
                daily_flows.append({'date': flow_date, 'main_net': float(v)})
            today_val = float(values.iloc[-1]) if len(values) > 0 else 0
            five_day = float(values.tail(5).sum()) if len(values) >= 5 else 0

            return {
                'main_net_inflow_today': today_val,
                'main_net_inflow_5day': five_day,
                'main_net_inflow_trend': self._judge_fund_trend(daily_flows),
                'super_large_net': float(super_values.iloc[-1]) if not super_values.empty else 0,
                'large_net': float(large_values.iloc[-1]) if not large_values.empty else 0,
                'has_data': True,
                'today_has_data': True,
                'five_day_has_data': len(values) >= 5,
                'available_days': int(len(values)),
                'source': 'akshare',
                'as_of_date': str(daily_flows[-1]['date']) if daily_flows else '',
            }
        except Exception as e:
            print(f"解析 akshare 资金流向失败: {e}")
            return self._empty_fund_flow()

    def _judge_fund_trend(self, daily_flows: list) -> str:
        """判断资金流向趋势"""
        if len(daily_flows) < 3:
            return '数据不足'

        recent = daily_flows[-5:] if len(daily_flows) >= 5 else daily_flows
        signs = [1 if d['main_net'] > 0 else -1 for d in recent]

        # 全部正 → 持续流入
        if all(s > 0 for s in signs):
            return '持续流入'
        # 全部负 → 持续流出
        if all(s < 0 for s in signs):
            return '持续流出'
        # 最近2天转正 → 转入
        if len(signs) >= 2 and signs[-1] > 0 and signs[-2] > 0 and any(s < 0 for s in signs[:-2]):
            return '转入'
        # 最近2天转负 → 转出
        if len(signs) >= 2 and signs[-1] < 0 and signs[-2] < 0 and any(s > 0 for s in signs[:-2]):
            return '转出'
        
        return '震荡'

    def _get_dragon_tiger(self, code: str) -> dict:
        """获取龙虎榜数据（近期）"""
        default = {
            'institution_net': 0,
            'northbound_net': 0,
            'hot_money_net': 0,
            'has_data': False,
        }

        try:
            # 尝试获取近期龙虎榜
            today = datetime.now()
            # 检查最近5个交易日是否有龙虎榜数据
            for i in range(5):
                check_date = (today - timedelta(days=i)).strftime('%Y%m%d')
                cache_key = f"lhb_detail_{check_date}"
                
                df = self.fetcher._get_cache(cache_key)
                if df is None:
                    try:
                        print(f"获取 {check_date} 龙虎榜数据...")
                        df = ak.stock_lhb_detail_em(
                            start_date=check_date, 
                            end_date=check_date
                        )
                        if df is not None:
                            self.fetcher._set_cache(cache_key, df)
                    except Exception as e:
                        print(f"从网络获取 {check_date} 龙虎榜失败: {e}")
                        df = pd.DataFrame()
                        self.fetcher._set_cache(cache_key, df)
                
                if df is not None and not df.empty:
                    # 过滤出目标股票
                    code_col = None
                    for col in df.columns:
                        if '代码' in str(col) or 'code' in str(col).lower():
                            code_col = col
                            break
                    
                    if code_col:
                        stock_df = df[df[code_col].astype(str).str.contains(code)]
                        if not stock_df.empty:
                            return self._parse_dragon_tiger(stock_df)

        except Exception as e:
            print(f"获取 {code} 龙虎榜失败: {e}")

        return default

    def _parse_dragon_tiger(self, df: pd.DataFrame) -> dict:
        """解析龙虎榜数据"""
        institution_net = 0
        northbound_net = 0
        hot_money_net = 0

        try:
            for _, row in df.iterrows():
                name = str(row.get('营业部名称', row.get('买方', '')))
                buy = float(row.get('买入额', 0) or 0)
                sell = float(row.get('卖出额', 0) or 0)
                net = buy - sell

                if '机构' in name:
                    institution_net += net
                elif '沪股通' in name or '深股通' in name or '港股通' in name:
                    northbound_net += net
                else:
                    hot_money_net += net

            return {
                'institution_net': institution_net,
                'northbound_net': northbound_net,
                'hot_money_net': hot_money_net,
                'has_data': True,
            }
        except Exception:
            return {
                'institution_net': 0,
                'northbound_net': 0,
                'hot_money_net': 0,
                'has_data': False,
            }

    def _get_margin_data(self, code: str) -> dict:
        """获取融资融券数据"""
        default = {
            'margin_balance': 0,
            'margin_balance_change': 0,
            'has_data': False,
        }

        try:
            # 尝试获取融资融券明细
            date_str = datetime.now().strftime('%Y%m%d')
            if code.startswith('6'):
                cache_key = f"margin_sse_{date_str}"
                df = self.fetcher._get_cache(cache_key)
                if df is None:
                    try:
                        print(f"从网络获取 {date_str} 上交所融资融券明细...")
                        df = ak.stock_margin_detail_sse(date=date_str)
                        if df is not None:
                            self.fetcher._set_cache(cache_key, df)
                    except Exception as e:
                        print(f"获取上交所融资融券明细失败: {e}")
                        df = pd.DataFrame()
                        self.fetcher._set_cache(cache_key, df)
            else:
                cache_key = f"margin_szse_{date_str}"
                df = self.fetcher._get_cache(cache_key)
                if df is None:
                    try:
                        print(f"从网络获取 {date_str} 深交所融资融券明细...")
                        df = ak.stock_margin_detail_szse(date=date_str)
                        if df is not None:
                            self.fetcher._set_cache(cache_key, df)
                    except Exception as e:
                        print(f"获取深交所融资融券明细失败: {e}")
                        df = pd.DataFrame()
                        self.fetcher._set_cache(cache_key, df)

            if df is not None and not df.empty:
                # 查找目标股票
                code_col = None
                for col in df.columns:
                    if '代码' in str(col) or 'code' in str(col).lower():
                        code_col = col
                        break
                
                if code_col:
                    stock_df = df[df[code_col].astype(str).str.contains(code)]
                    if not stock_df.empty:
                        row = stock_df.iloc[0]
                        # 查找融资余额列
                        balance_col = None
                        for col in df.columns:
                            if '融资余额' in str(col):
                                balance_col = col
                                break
                        
                        balance = float(row.get(balance_col, 0) or 0) if balance_col else 0
                        return {
                            'margin_balance': balance,
                            'margin_balance_change': 0,  # 需要对比历史
                            'has_data': True,
                        }
        except Exception as e:
            print(f"获取 {code} 融资融券失败: {e}")

        return default

    def _determine_signal(self, fund_flow: dict, dragon_tiger: dict, 
                          margin: dict) -> str:
        """
        判断资金博弈信号
        
        信号矩阵:
        - 强势共识: 主力+机构+北向都在买
        - 分歧博弈: 机构买但游资卖，或反之
        - 游资主导: 只有游资在买
        - 多方撤退: 主力+机构+融资都在卖
        - 散户接盘: 聪明钱卖，散户买
        """
        main_today = fund_flow.get('main_net_inflow_today', 0) if fund_flow.get('today_has_data') else None
        main_5day = fund_flow.get('main_net_inflow_5day', 0) if fund_flow.get('five_day_has_data') else None
        trend = fund_flow.get('main_net_inflow_trend', '')
        
        inst_net = dragon_tiger.get('institution_net', 0)
        north_net = dragon_tiger.get('northbound_net', 0)
        hot_money = dragon_tiger.get('hot_money_net', 0)
        has_lhb = dragon_tiger.get('has_data', False)
        
        margin_change = margin.get('margin_balance_change', 0)

        # 强势共识: 主力流入 + (机构或北向买入)
        if main_today is not None and main_5day is not None and main_today > 0 and main_5day > 0:
            if has_lhb and (inst_net > 0 or north_net > 0):
                return '强势共识'
            if trend == '持续流入':
                return '强势共识'

        # 多方撤退: 主力持续流出
        if main_today is not None and main_5day is not None and main_today < 0 and main_5day < 0:
            if has_lhb and inst_net < 0:
                return '多方撤退'
            if trend == '持续流出':
                return '多方撤退'

        # 散户接盘: 机构/北向卖，但主力流入（可能是散户抄底）
        if has_lhb and (inst_net < 0 and north_net < 0) and hot_money > 0:
            return '散户接盘'

        # 分歧博弈
        if has_lhb and inst_net > 0 and hot_money < 0:
            return '分歧博弈'
        if has_lhb and inst_net < 0 and hot_money > 0:
            return '分歧博弈'

        # 游资主导
        if has_lhb and hot_money > 0 and inst_net == 0 and north_net == 0:
            return '游资主导'

        # 默认根据主力流向判断
        if main_today is not None and main_today > 0:
            return '分歧博弈'
        elif main_today is not None and main_today < 0:
            return '多方撤退'
        
        return '数据不足'

    def _calculate_score(self, fund_flow: dict, dragon_tiger: dict, 
                         margin: dict, signal: str) -> int:
        """计算个股资金综合得分 (0-100)"""
        score = 50  # 基准分

        main_today = fund_flow.get('main_net_inflow_today', 0)
        trend = fund_flow.get('main_net_inflow_trend', '')
        
        has_lhb = dragon_tiger.get('has_data', False)
        inst_net = dragon_tiger.get('institution_net', 0)
        north_net = dragon_tiger.get('northbound_net', 0)

        # === 1. 今日主力资金 (±15分) ===
        if fund_flow.get('today_has_data'):
            if main_today > 100_000_000:      # 净流入 > 1亿
                score += 15
            elif main_today > 50_000_000:     # 净流入 > 5000万
                score += 12
            elif main_today > 0:
                score += 8
            elif main_today > -50_000_000:
                score -= 8
            elif main_today > -100_000_000:
                score -= 12
            else:                              # 净流出 > 1亿
                score -= 15

        # === 2. 5日趋势 (±10分) ===
        if fund_flow.get('five_day_has_data'):
            if trend == '持续流入':
                score += 10
            elif trend == '转入':
                score += 7
            elif trend == '震荡':
                score += 0
            elif trend == '转出':
                score -= 7
            elif trend == '持续流出':
                score -= 10

        # === 3. 龙虎榜 (±10分) ===
        if has_lhb:
            if inst_net > 0:
                score += 8
            elif inst_net < 0:
                score -= 8
            
            if north_net > 0:
                score += 5
            elif north_net < 0:
                score -= 3

        # === 4. 融资 (±5分) ===
        margin_change = margin.get('margin_balance_change', 0)
        if margin.get('has_data'):
            if margin_change > 0:
                score += 5
            elif margin_change < 0:
                score -= 5

        # === 5. 信号调整 (±10分) ===
        signal_adj = {
            '强势共识': 5,
            '分歧博弈': 0,
            '游资主导': -3,
            '多方撤退': -10,
            '散户接盘': -10,
            '数据不足': 0,
        }
        score += signal_adj.get(signal, 0)

        return max(0, min(100, score))


# ========== 测试代码 ==========
if __name__ == "__main__":
    print("=" * 60)
    print("个股资金动态分析测试")
    print("=" * 60)

    fetcher = DataFetcher()
    analyzer = StockFundAnalyzer(fetcher)

    test_codes = ['603083', '002706']
    for code in test_codes:
        print(f"\n--- 测试 {code} ---")
        result = analyzer.analyze(code)
        print(f"  得分: {result['score']}")
        print(f"  信号: {result['signal']}")
        
        ff = result['fund_flow']
        main_yi = ff['main_net_inflow_today'] / 100_000_000 if ff.get('today_has_data') else None
        main5_yi = ff['main_net_inflow_5day'] / 100_000_000 if ff.get('five_day_has_data') else None
        print(f"  今日主力: {main_yi:.2f}亿" if main_yi is not None else "  今日主力: --")
        print(f"  5日主力: {main5_yi:.2f}亿" if main5_yi is not None else "  5日主力: --")
        print(f"  趋势: {ff['main_net_inflow_trend']}")

        dt = result['dragon_tiger']
        if dt['has_data']:
            print(f"  龙虎榜: 机构{dt['institution_net']/10000:.0f}万 北向{dt['northbound_net']/10000:.0f}万 游资{dt['hot_money_net']/10000:.0f}万")
        else:
            print(f"  龙虎榜: 无近期数据")
