"""
逆势英雄选股引擎
在大盘暴跌日找出"该跌不跌"甚至逆势涨停的强势股

核心逻辑：
1. 大盘暴跌（沪指或深成指跌幅 ≥ 2%）
2. 个股逆势走强（涨幅 > 3%，涨停最佳）
3. 成交量温和放大（剔除天量换手的虚假强势）
4. 非补涨反弹（近 10 日相对表现未大幅跑输）

使用场景：
- 盘后复盘，筛选次日竞价分歧转一致的标的
- 构建"暴跌后的强者池"
"""

from typing import List, Dict, Optional
from data_fetcher import DataFetcher
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import pickle
import re
import requests
import time

from logger_config import get_logger
logger = get_logger(__name__)


class CounterTrendHeroScanner:
    """逆势英雄扫描器"""

    def __init__(self, data_fetcher: DataFetcher = None):
        self.fetcher = data_fetcher or DataFetcher()
        self.cache_dir = Path(__file__).parent / "cache"
        self.cache_dir.mkdir(exist_ok=True)

    def _get_cache_path(self, cache_key: str) -> Path:
        """获取缓存文件路径"""
        return self.cache_dir / f"hero_{cache_key}.pkl"

    def _load_from_cache(self, cache_key: str, max_age_minutes: int = 30) -> Optional[pd.DataFrame]:
        """从缓存加载数据"""
        cache_file = self._get_cache_path(cache_key)
        if not cache_file.exists():
            return None

        try:
            # 检查缓存年龄
            cache_age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
            if cache_age > timedelta(minutes=max_age_minutes):
                logger.info(f"   [INFO] 缓存已过期（{int(cache_age.total_seconds() / 60)} 分钟前）")
                return None

            with open(cache_file, 'rb') as f:
                data = pickle.load(f)
                logger.info(f"   [OK] 从缓存加载数据（{int(cache_age.total_seconds() / 60)} 分钟前）")
                return data
        except Exception as e:
            logger.warning(f"   [WARN] 缓存加载失败: {e}")
            return None

    def _save_to_cache(self, cache_key: str, data: pd.DataFrame):
        """保存数据到缓存"""
        try:
            cache_file = self._get_cache_path(cache_key)
            with open(cache_file, 'wb') as f:
                pickle.dump(data, f)
            logger.info(f"   [OK] 数据已缓存")
        except Exception as e:
            logger.warning(f"   [WARN] 缓存保存失败: {e}")

    def _fetch_prior_metrics(
        self, codes: List[str], lookback_days: int, current_volume_map: Dict[str, float], max_workers: int = 10
    ) -> Dict[str, Dict[str, Optional[float]]]:
        """并发获取近期表现和量比。

        用于"剔除利空出尽型"：若前期已暴跌，今日大涨多为超跌反弹而非真强势。
        获取失败的股票保留 None（不剔除，宁可保留待人工判断）。
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _one(code: str) -> Dict[str, Optional[float]]:
            metrics = {'prior_change': None, 'volume_ratio': None}
            try:
                df = self.fetcher.get_stock_history(code, days=lookback_days + 5)
                if df is None or len(df) < 3:
                    return metrics

                closes = df['close'].astype(float)
                last_date = pd.to_datetime(df['date'].iloc[-1]).date() if 'date' in df.columns else None
                last_is_today = last_date == datetime.now().date()
                end_pos = len(closes) - 2 if last_is_today and len(closes) >= 2 else len(closes) - 1

                # 不含今日：有当日K线时用倒数第2根作为"昨收"，否则用最新历史K线
                end = closes.iloc[end_pos]
                start_idx = max(0, end_pos - lookback_days)
                start = closes.iloc[start_idx]
                if start > 0:
                    metrics['prior_change'] = (end - start) / start * 100

                if 'volume' in df.columns and len(df) >= 6:
                    history_volumes = df['volume'].astype(float)
                    if last_is_today and len(history_volumes) >= 6:
                        avg5 = history_volumes.iloc[-6:-1].mean()
                    else:
                        avg5 = history_volumes.iloc[-5:].mean()
                    current_volume = current_volume_map.get(code, 0.0)
                    if avg5 and avg5 > 0 and current_volume > 0:
                        metrics['volume_ratio'] = current_volume / avg5

                return metrics
            except Exception:
                return metrics

        result: Dict[str, Dict[str, Optional[float]]] = {}
        if not codes:
            return result
        workers = max(1, min(max_workers, len(codes)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_one, code): code for code in codes}
            for future in as_completed(futures):
                code = futures[future]
                try:
                    result[code] = future.result()
                except Exception:
                    result[code] = {'prior_change': None, 'volume_ratio': None}
        return result

    def _fetch_prior_changes(
        self, codes: List[str], lookback_days: int, max_workers: int = 10
    ) -> Dict[str, Optional[float]]:
        metrics = self._fetch_prior_metrics(codes, lookback_days, {}, max_workers=max_workers)
        return {code: item.get('prior_change') for code, item in metrics.items()}

    def _sina_symbol_batches(self, batch_size: int = 500):
        ranges = [
            ("sh", 600000, 605999),
            ("sh", 688000, 689999),
            ("sz", 0, 3999),
            ("sz", 300000, 301999),
        ]
        for prefix, start, end in ranges:
            batch = []
            for code in range(start, end + 1):
                batch.append(f"{prefix}{code:06d}")
                if len(batch) >= batch_size:
                    yield batch
                    batch = []
            if batch:
                yield batch

    @staticmethod
    def _is_active_sina_quote(symbol: str, parts: List[str]) -> bool:
        if not parts or not parts[0]:
            return False
        if len(parts) < 33 or parts[32] == "-3":
            return False
        return symbol.startswith(("sh", "sz")) and parts[32] == "00"

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _fetch_sina_index_changes(self) -> Dict[str, float]:
        url = "http://hq.sinajs.cn/list=s_sh000001,s_sz399001"
        headers = {
            'Referer': 'http://finance.sina.com.cn',
            'User-Agent': 'Mozilla/5.0',
        }
        result = self.fetcher.source_client.get(
            "sina",
            url,
            headers=headers,
            timeout=8,
            retries=2,
            min_interval=0.02,
            allow_when_open=True,
        )
        if not result.ok:
            raise RuntimeError(result.error or "新浪指数接口失败")

        text = result.response.content.decode('gbk', errors='ignore')
        changes = {'sh': 0.0, 'sz': 0.0}
        for symbol, data in re.findall(r'var hq_str_([^=]+)="([^"]*)";', text):
            parts = data.split(',')
            if len(parts) < 4:
                continue
            if symbol == 's_sh000001':
                changes['sh'] = self._safe_float(parts[3])
            elif symbol == 's_sz399001':
                changes['sz'] = self._safe_float(parts[3])
        return changes

    def _fetch_sina_market_spot(self) -> pd.DataFrame:
        """Fetch full A-share realtime quotes from Sina with turnover ratio."""
        rows = []
        headers = {
            'Referer': 'http://finance.sina.com.cn',
            'User-Agent': 'Mozilla/5.0',
        }
        base_url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
        # Sina accepts num=200 but currently returns at most 100 records per page.
        page_size = 100

        for node in ("hs_a",):
            count_url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeStockCount"
            count_resp = requests.get(
                count_url,
                params={"node": node},
                headers=headers,
                timeout=15,
                proxies={"http": None, "https": None},
            )
            count_resp.raise_for_status()
            total = int(count_resp.text.strip().strip('"'))
            pages = (total + page_size - 1) // page_size

            for page in range(1, pages + 1):
                params = {
                    "page": page,
                    "num": page_size,
                    "sort": "symbol",
                    "asc": 1,
                    "node": node,
                    "symbol": "",
                    "_s_r_a": "page",
                }
                result = self.fetcher.source_client.get(
                    "sina",
                    base_url,
                    params=params,
                    headers=headers,
                    timeout=15,
                    retries=2,
                    min_interval=0.02,
                    allow_when_open=True,
                )
                if not result.ok:
                    raise RuntimeError(result.error or "新浪行情分页接口失败")

                items = result.response.json()
                for item in items or []:
                    code = str(item.get('code') or '').zfill(6)
                    current = self._safe_float(item.get('trade'))
                    if len(code) != 6 or current <= 0:
                        continue
                    rows.append({
                        '代码': code,
                        '名称': str(item.get('name') or '').strip(),
                        '最新价': current,
                        '涨跌幅': self._safe_float(item.get('changepercent')),
                        '换手率': self._safe_float(item.get('turnoverratio')),
                        '量比': 1.0,
                        '成交量': self._safe_float(item.get('volume')),
                        '成交额': self._safe_float(item.get('amount')),
                    })

                time.sleep(0.02)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows).drop_duplicates(subset=['代码'], keep='first')
        return df.reset_index(drop=True)

    def scan(
        self,
        min_gain_pct: float = 3.0,
        max_turnover: float = 25.0,
        lookback_days: int = 10,
    ) -> Dict:
        """
        扫描逆势英雄股

        Args:
            min_gain_pct: 最低涨幅（%），默认 3%
            max_turnover: 最大换手率（%），剔除天量换手，默认 25%
            lookback_days: 回溯天数，用于判断是否补涨，默认 10 天

        Returns:
            {
                'success': bool,
                'market_condition': '暴跌' | '震荡' | '上涨',
                'index_change': {
                    'sh': float,  # 沪指涨跌幅
                    'sz': float,  # 深成指涨跌幅
                },
                'heroes': [
                    {
                        'code': str,
                        'name': str,
                        'change_pct': float,      # 涨跌幅
                        'turnover': float,        # 换手率
                        'volume_ratio': float,    # 量比
                        'is_limit_up': bool,      # 是否涨停
                        'seal_amount': float,     # 封单金额（亿）
                        'relative_strength': float, # 近 N 日相对表现
                        'sector': str,            # 所属板块
                        'hero_level': str,        # 英雄等级：涨停英雄/大涨英雄/抗跌英雄
                        'score': float,           # 综合评分
                    },
                    ...
                ],
                'count': int,
                'timestamp': str,
            }
        """
        import akshare as ak

        logger.info("=== 逆势英雄扫描 ===")

        # Step 1: 判断市场环境
        logger.info("[1/4] 判断市场环境...")
        sh_change = sz_change = 0
        market_condition = '未知'

        try:
            index_changes = self._fetch_sina_index_changes()
            sh_change = index_changes['sh']
            sz_change = index_changes['sz']

            avg_change = (sh_change + sz_change) / 2

            if avg_change <= -2.0:
                market_condition = '暴跌'
                logger.info(f"   [OK] 市场暴跌（沪指 {sh_change:.2f}%，深成指 {sz_change:.2f}%）")
            elif avg_change <= -1.0:
                market_condition = '调整'
                logger.info(f"   [WARN] 市场调整（沪指 {sh_change:.2f}%，深成指 {sz_change:.2f}%）")
            else:
                market_condition = '非暴跌'
                logger.info(f"   [INFO] 非暴跌日（沪指 {sh_change:.2f}%，深成指 {sz_change:.2f}%）")
                logger.info("   提示：逆势英雄策略更适合暴跌日使用")

        except Exception as e:
            logger.warning(f"   [WARN] 新浪指数获取失败: {e}")
            try:
                # 使用 akshare 作为指数兜底
                df_index = ak.stock_zh_index_spot_em()

                # 查找上证指数和深成指
                sh_data = df_index[df_index['代码'] == '000001']
                sz_data = df_index[df_index['代码'] == '399001']

                sh_change = float(sh_data['涨跌幅'].values[0]) if not sh_data.empty else 0
                sz_change = float(sz_data['涨跌幅'].values[0]) if not sz_data.empty else 0
            except Exception as index_error:
                logger.warning(f"   [WARN] 获取指数失败: {index_error}")
                logger.info("   [INFO] 继续扫描（无市场环境判断）...")

        # Step 2: 获取全市场行情
        logger.info("[2/4] 获取全市场行情...")
        df_spot = None
        error_msg = ""

        # 策略：优先新浪 → akshare → 缓存（新浪更稳定）

        # 方法1：尝试使用新浪数据（批量获取全市场行情）
        try:
            logger.info("   尝试从新浪批量获取全A实时行情...")
            df_spot = self._fetch_sina_market_spot()
            if df_spot is None or len(df_spot) < 100:
                count = 0 if df_spot is None else len(df_spot)
                raise ValueError(f"新浪接口返回数据不足（仅 {count} 只）")

            logger.info(f"   [OK] 获取 {len(df_spot)} 只股票实时行情（新浪分页数据）")
            self._save_to_cache('market_spot', df_spot)

        except Exception as e:
            logger.warning(f"   [WARN] 新浪接口失败: {e}")
            import traceback
            traceback.print_exc()

        # 方法2：如果新浪失败，尝试 akshare
        if df_spot is None or len(df_spot) == 0:
            try:
                logger.info("   尝试从 akshare 获取...")
                df_spot = ak.stock_zh_a_spot_em()
                if df_spot is None or len(df_spot) == 0:
                    raise ValueError("获取的行情数据为空")
                logger.info(f"   [OK] 获取 {len(df_spot)} 只股票行情（akshare）")
                self._save_to_cache('market_spot', df_spot)
            except Exception as e:
                error_msg = str(e)
                logger.warning(f"   [ERROR] akshare 获取失败: {error_msg}")

        # 方法3：如果都失败，使用缓存
        if df_spot is None or len(df_spot) == 0:
            logger.info("   [INFO] 尝试使用缓存数据...")
            df_spot = self._load_from_cache('market_spot', max_age_minutes=480)

        # 如果还是没有数据，返回错误
        if df_spot is None or len(df_spot) == 0:
            if 'Connection' in error_msg or 'Remote' in error_msg:
                friendly_error = "网络连接失败且无可用缓存。数据源暂时不可用。建议：1) 在交易时段（9:30-15:00）重试 2) 检查网络连接 3) 稍后再试"
            else:
                friendly_error = f"数据获取失败且无可用缓存: {error_msg if error_msg else '所有数据源均不可用'}"

            return {
                'success': False,
                'error': friendly_error,
                'market_condition': market_condition,
                'index_change': {'sh': sh_change, 'sz': sz_change},
            }

        # Step 3: 初筛——该跌不跌
        logger.info(f"[3/4] 筛选逆势股（涨幅 > {min_gain_pct}%）...")
        filtered = df_spot[
            (df_spot['涨跌幅'] > min_gain_pct) &                  # 逆势上涨
            (df_spot['换手率'] < max_turnover) &                  # 剔除天量换手
            (df_spot['最新价'] > 3) &                            # 价格 > 3元
            (df_spot['成交额'] > 50000000) &                     # 成交额 > 5000万
            (~df_spot['代码'].str.startswith(('4', '8', '92', '688'))) &  # 排除北交所、科创板
            (~df_spot['名称'].str.contains('ST|退', na=False)) &  # 排除ST/退市
            (~df_spot['名称'].str.match(r'^[NC]', na=False))      # 排除新股(N)和次新上市初期(C)
        ]

        logger.info(f"   [OK] 初筛通过: {len(filtered)} 只")

        if len(filtered) == 0:
            return {
                'success': True,
                'market_condition': market_condition,
                'index_change': {'sh': sh_change, 'sz': sz_change},
                'heroes': [],
                'count': 0,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            }

        # Step 4: 精细评分
        logger.info(f"[4/4] 精细评分（剔除补涨、评估强度）...")

        # 涨停池只取一次（旧版在循环内每只股票都拉一次）
        zt_seal_map = {}
        try:
            zt_pool = self.fetcher.get_limit_up_pool()
            for stock in zt_pool or []:
                zt_seal_map[stock.get('code')] = stock.get('seal_amount', 0)
        except Exception:
            pass

        # 并发预取近期K线，用于"剔除利空出尽型"（前期超跌、今日只是反弹）和计算量比
        candidate_codes = filtered['代码'].tolist()
        current_volume_map = dict(zip(filtered['代码'], filtered.get('成交量', pd.Series(dtype=float))))
        prior_metric_map = self._fetch_prior_metrics(candidate_codes, lookback_days, current_volume_map)

        heroes = []

        for _, row in filtered.iterrows():
            code = row['代码']
            name = row['名称']
            change_pct = row['涨跌幅']
            turnover = row['换手率']
            volume_ratio = row.get('量比', 1.0)
            current_price = row['最新价']

            # 板块感知的涨停判定（主板10%、创业板20%）
            limit_threshold = 19.5 if str(code).startswith(('30', '301')) else 9.5
            is_limit_up = change_pct >= limit_threshold
            seal_amount = 0.0
            if is_limit_up and code in zt_seal_map:
                seal_amount = zt_seal_map[code] / 100000000  # 转为亿

            # 深度过滤①：剔除利空出尽型（前期暴跌后的超跌反弹，非真强势）
            prior_metrics = prior_metric_map.get(code, {})
            prior_change = prior_metrics.get('prior_change')
            relative_strength = prior_change if prior_change is not None else 0.0
            is_oversold_rebound = prior_change is not None and prior_change <= -15.0
            if is_oversold_rebound:
                continue  # 近N日已暴跌超15%，今日大涨大概率是超跌反弹，剔除

            metric_volume_ratio = prior_metrics.get('volume_ratio')
            if metric_volume_ratio is not None and metric_volume_ratio > 0:
                volume_ratio = metric_volume_ratio

            # 板块（简化处理）
            sector = row.get('所属行业', '未知')

            # 英雄等级（文章"第三步：优选排序"）
            if is_limit_up:
                hero_level = '涨停英雄'   # 第一等：黄金标准
                base_score = 100
            elif change_pct >= 7:
                hero_level = '大涨英雄'
                base_score = 85
            elif change_pct >= 5:
                hero_level = '强势英雄'   # 第二等：逆势大涨
                base_score = 75
            else:
                hero_level = '抗跌英雄'
                base_score = 60

            # 综合评分
            score = base_score

            # 封单坚决度加分（涨停英雄内部分层）
            if is_limit_up:
                if seal_amount >= 5:
                    score += 10
                elif seal_amount >= 1:
                    score += 5

            # 量能审查（文章：温和放量最佳，天量警惕次日补跌）
            if 1.5 <= volume_ratio <= 3.0:
                score += 10   # 温和放量：筹码锁定好
            elif volume_ratio > 5.0:
                score -= 15   # 天量：主力承接成本过高，次日易补跌
            elif volume_ratio > 4.0:
                score -= 5

            # 换手率加分（适中最佳）
            if 3 <= turnover <= 15:
                score += 5
            elif turnover > 20:
                score -= 5

            # 前期走势加分：横盘或趋势向上中的抗跌才是真强
            if prior_change is not None and -5 <= prior_change <= 20:
                score += 5

            heroes.append({
                'code': code,
                'name': name,
                'change_pct': round(float(change_pct), 2),
                'turnover': round(float(turnover), 2),
                'volume_ratio': round(float(volume_ratio), 2),
                'is_limit_up': bool(is_limit_up),
                'seal_amount': round(float(seal_amount), 2),
                'relative_strength': round(float(relative_strength), 2),
                'sector': sector,
                'hero_level': hero_level,
                'score': round(float(score), 1),
                'current_price': round(float(current_price), 2),
            })

        # 按评分排序
        heroes.sort(key=lambda x: x['score'], reverse=True)

        logger.info(f"   [OK] 发现 {len(heroes)} 只逆势英雄")
        logger.info(f"      涨停英雄: {sum(1 for h in heroes if h['hero_level'] == '涨停英雄')} 只")
        logger.info(f"      大涨英雄: {sum(1 for h in heroes if h['hero_level'] == '大涨英雄')} 只")

        return {
            'success': True,
            'market_condition': market_condition,
            'index_change': {
                'sh': round(sh_change, 2),
                'sz': round(sz_change, 2),
            },
            'heroes': heroes,
            'count': len(heroes),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }


if __name__ == '__main__':
    scanner = CounterTrendHeroScanner()
    result = scanner.scan(min_gain_pct=3.0)

    if result['success']:
        print(f"\n{'='*60}")
        print(f"市场状态: {result['market_condition']}")
        print(f"沪指: {result['index_change']['sh']}%  |  深成指: {result['index_change']['sz']}%")
        print(f"发现 {result['count']} 只逆势英雄")
        print(f"{'='*60}\n")

        for i, hero in enumerate(result['heroes'][:10], 1):
            print(f"{i}. {hero['code']} {hero['name']}")
            print(f"   涨幅: {hero['change_pct']}%  |  换手: {hero['turnover']}%  |  量比: {hero['volume_ratio']}")
            print(f"   等级: {hero['hero_level']}  |  评分: {hero['score']}")
            print()
