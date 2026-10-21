"""
网络策略：国内行情网站一律直连，不走系统代理（Clash 等）。

为什么：项目自己的取数客户端（DataSourceClient）本来就直连，但 AKShare 内部用的是普通 requests，
会读取 Windows 系统代理。经代理访问东方财富、上交所、深交所时又慢又不稳——
全市场快照 59 页要 70~90 秒、上交所常报 ProxyError、深交所读超时，一个请求就能占住服务线程几十秒。

做法：服务启动时把国内行情域名写进 NO_PROXY。requests / urllib 对这些域名会跳过代理
（系统代理和环境变量代理都适用），访问境外网站仍按原来的代理走。
设 IRONTRADER_DIRECT_DOMESTIC=0 可以关闭。
"""

from __future__ import annotations

import os
from typing import List, MutableMapping, Optional

# 只列国内行情 / 资讯 / 交易所域名（后缀匹配：eastmoney.com 覆盖 push2.eastmoney.com 等子域名）
DOMESTIC_MARKET_DOMAINS = (
    "eastmoney.com",      # 东方财富：行情、涨停池、资金流、公告
    "sse.com.cn",         # 上交所
    "szse.cn",            # 深交所
    "bse.cn",             # 北交所
    "sina.com.cn",        # 新浪财经：分页行情、日 K、交易日历
    "sinajs.cn",          # 新浪实时行情
    "gtimg.cn",           # 腾讯行情、日 K
    "gu.qq.com",          # 腾讯自选股页面（行情接口的 Referer 来源）
    "10jqka.com.cn",      # 同花顺数据
    "cninfo.com.cn",      # 巨潮资讯
    "csindex.com.cn",     # 中证指数
    "cnindex.com.cn",     # 国证指数
    "legulegu.com",       # 乐咕乐股（AKShare 部分指标）
)


def _split(value: Optional[str]) -> List[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def apply_domestic_direct(env: Optional[MutableMapping[str, str]] = None) -> List[str]:
    """把国内行情域名并入 NO_PROXY / no_proxy（保留已有条目）。返回生效后的列表；关闭时返回空列表。"""
    env = os.environ if env is None else env
    if env.get("IRONTRADER_DIRECT_DOMESTIC", "1").strip() == "0":
        return []
    merged: List[str] = []
    for item in _split(env.get("NO_PROXY")) + _split(env.get("no_proxy")) + list(DOMESTIC_MARKET_DOMAINS):
        if item not in merged:
            merged.append(item)
    value = ",".join(merged)
    env["NO_PROXY"] = value
    env["no_proxy"] = value
    return merged


__all__ = ["DOMESTIC_MARKET_DOMAINS", "apply_domestic_direct"]
