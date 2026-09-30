"""
消息面刺激：抓取个股公告 / 新闻 → 规则分类 → 加权打分；以及全市场"重大消息雷达"。

第一版是【观察模式】：只展示、只提醒，不改变龙头 / 低吸 / 执行闸的任何结论。
为什么先只观察：消息的方向和力度很依赖上下文（同一条"减持"对大盘股和小票影响完全不同，
"利好兑现"也很常见），规则打分需要作者看一段时间、调好权重之后，再决定要不要接进结论。
接入原系统的几种方案见 docs/消息面权重设计.md。

打分公式（每条消息）：
    贡献 = 方向(+1/-1) × 等级分(LEVEL_POINTS) × 来源权重(SOURCE_WEIGHT) × 时间衰减
    时间衰减 = 0.5 ** (已过交易日 / 半衰期)       —— 半衰期按事件类型不同（立案调查很长、中标很短）
汇总（个股）：
    同一类型的多条消息只算最强的一条 + 其余的 25%（媒体转载同一公告不会被重复计分）
    消息面分数 = 100 × tanh(各类型之和 / 50)，落在 -100 ~ +100

数据源：
    公告  东方财富公告中心（有分类标签、有发布时间）→ 失败时用巨潮资讯（证监会指定披露平台）
    新闻  东方财富资讯搜索（媒体报道，可信度打折，只收标题里出现股票名称的）
"""

from __future__ import annotations

import json
import math
import re
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from data_source_client import DataSourceClient
from logger_config import get_logger

logger = get_logger(__name__)

TZ = ZoneInfo("Asia/Shanghai")

# ---------------------------------------------------------------------------
# 可调参数（改这里就能调权重；每个参数的含义见 docs/消息面权重设计.md）
# ---------------------------------------------------------------------------

LEVEL_POINTS = {"major": 40, "notable": 20, "minor": 8, "noise": 0}
LEVEL_LABEL = {"major": "重大", "notable": "显著", "minor": "一般", "noise": "噪音"}
SOURCE_WEIGHT = {"announcement": 1.0, "news": 0.5}
SOURCE_LABEL = {"announcement": "公告", "news": "新闻"}
SAME_TYPE_EXTRA = 0.25      # 同类型第 2 条起只按 25% 计入
SCORE_SCALE = 50.0          # tanh 的缩放：一条新鲜的重大消息（40 分）约等于 ±66
ACTIVE_DECAY = 0.25         # 衰减到 25% 以下视为"已过时效"，不再算作重大提醒
ANN_LOOKBACK_DAYS = 30
NEWS_LOOKBACK_DAYS = 7
NEWS_NAME_MAX_POS = 8       # 新闻标题里股票名称最晚出现在第几个字之前，才算"讲的是这只股票"


@dataclass(frozen=True)
class Rule:
    type: str
    label: str
    direction: int          # +1 利好 / -1 利空 / 0 方向需看正文
    level: str              # major / notable / minor / noise
    half_life: float        # 以交易日计
    pattern: str            # 标题正则
    exclude: str = ""       # 标题命中这里则跳过本规则
    columns: Tuple[str, ...] = ()  # 东财公告分类命中其一也算（标题正则或分类任一命中即可）


# 顺序即优先级：越具体的放越前面（例如"撤销退市风险警示"必须排在"退市风险警示"之前）
RULES: Tuple[Rule, ...] = (
    # ---- 反转类（带"终止/撤销/不"的，先于正向规则判断）----
    Rule("st_removed", "撤销风险警示（摘帽）", +1, "major", 5, r"撤销.{0,6}(退市风险警示|其他风险警示)|申请撤销.{0,4}风险警示"),
    Rule("reduce_stopped", "终止/不减持", +1, "minor", 2, r"(终止|提前终止|放弃|不)(实施)?.{0,6}减持"),
    Rule("restructure_stopped", "终止重组/收购/发行", -1, "notable", 3,
         r"终止.{0,12}(重大资产重组|重组|发行股份|购买资产|收购|定增|向特定对象发行|控制权)"),
    Rule("buyback_stopped", "终止回购/增持", -1, "minor", 2, r"终止.{0,8}(回购|增持)"),

    # ---- 重大利空 ----
    Rule("delisting", "退市风险", -1, "major", 10,
         r"退市风险警示|终止上市|可能被终止上市|面值退市|强制退市|进入退市整理"),
    Rule("st", "实施其他风险警示（戴帽）", -1, "major", 10, r"实施其他风险警示|被实施.{0,4}风险警示|股票简称.{0,6}ST"),
    Rule("investigation", "立案调查 / 强制措施", -1, "major", 10,
         r"立案|留置|刑事强制措施|被采取.{0,4}强制措施|被公安机关|失联|无法履职",
         exclude=r"诉讼|仲裁|受理|起诉"),
    Rule("trading_halt_check", "停牌核查", -1, "notable", 3, r"停牌核查"),
    Rule("default", "债务违约 / 资金链", -1, "major", 5,
         r"债务逾期|未能.{0,4}(兑付|偿还)|无法按期|违约|资金占用|非经营性占用|被申请破产"),
    Rule("penalty", "行政处罚 / 纪律处分", -1, "notable", 5,
         r"行政处罚|处罚事先告知|公开谴责|纪律处分|通报批评|市场禁入|处罚",
         exclude=r"不存在|最近[一二三四五]年"),
    Rule("earnings_down", "业绩预减 / 亏损", -1, "notable", 3,
         r"(预亏|首亏|续亏|预减|亏损|大幅下降|同比下降|业绩下滑)", exclude=r"减亏|扭亏"),
    Rule("reduce_plan", "股东减持计划", -1, "notable", 3,
         r"减持.{0,6}(计划|预披露)|拟减持|大股东.{0,4}减持|控股股东.{0,6}减持|清仓",
         exclude=r"(减持|计划).{0,4}(结果|完成|实施完毕|届满)"),
    Rule("frozen", "股份冻结 / 被动减持", -1, "notable", 3,
         r"司法冻结|轮候冻结|股份.{0,4}冻结|司法拍卖|被动减持|强制平仓|平仓风险", exclude=r"解除"),
    Rule("reduce_progress", "减持进展 / 结果", -1, "minor", 2,
         r"减持", columns=("股东/实际控制人股份减持",)),
    Rule("unlock", "限售股解禁", -1, "minor", 2, r"限售.{0,6}上市流通|解除限售|解禁", columns=("限售股份上市流通",)),
    Rule("severe_abnormal", "严重异常波动 / 风险提示", -1, "notable", 1, r"严重异常波动"),
    Rule("inquiry", "问询 / 监管函", -1, "minor", 2, r"(问询函|关注函|监管函|警示函|监管工作函)",
         exclude=r"回复|答复"),
    Rule("abnormal", "异常波动 / 风险提示", -1, "minor", 1, r"异常波动|风险提示", exclude=r"一般风险提示",
         columns=("股票交易异常波动", "其它风险提示公告")),
    Rule("lawsuit", "诉讼 / 仲裁", -1, "minor", 2, r"诉讼|仲裁", exclude=r"进展|结果|判决.*胜诉", columns=("诉讼仲裁",)),
    Rule("exec_resign", "董事长/总经理离任", -1, "minor", 2,
         r"(董事长|总经理|总裁|实际控制人).{0,6}(辞职|辞去|离任|被免)"),

    # ---- 重大利好 ----
    Rule("restructure", "重大资产重组 / 购买资产", +1, "major", 5,
         r"重大资产重组|发行股份.{0,6}购买资产|重组预案|资产重组|重大资产购买",
         # 一次重组会配套几十份程序性文件，只认"预案 / 草案首版 / 审核通过 / 注册"这类主文件
         exclude=r"进展|问询|回复|不构成|法律意见|财务顾问|核查|说明|修订|前十大|暂不召开|评估师|审计|意见|承诺|摘要|自查|符合|出售"),
    Rule("control_change", "控制权变更", +1, "major", 5,
         r"控制权.{0,4}(变更|发生变化|拟发生)|实际控制人.{0,6}变更|控股股东.{0,6}变更|筹划.{0,10}控制权",
         exclude=r"进展"),
    Rule("major_plan_halt", "筹划重大事项停牌", +1, "major", 5, r"筹划.{0,16}停牌"),
    Rule("earnings_up", "业绩预增 / 扭亏", +1, "notable", 3, r"预增|扭亏|大幅增长|同比增长|业绩大增|预盈"),
    Rule("big_contract", "中标 / 重大合同", +1, "notable", 2,
         r"中标|重大合同|签订.{0,12}(合同|协议)|战略合作|框架协议|获得.{0,6}订单|定点",
         exclude=r"进展|监管协议|募集资金|托管|担保|借款|委托|转让|表决权|一致行动|补充协议", columns=("重大合同",)),
    Rule("approval", "产品获批 / 注册", +1, "notable", 2,
         r"获得.{0,12}(注册证|批件|批准|认证)|药品注册|获批|临床试验.{0,6}(批准|许可|默示)|一致性评价|FDA|CE认证",
         exclude=r"发行|定增|股东会|股东大会|注册资本|募集|可转债|债券"),
    Rule("increase_holding", "股东增持", +1, "minor", 2, r"增持", exclude=r"完成|结果|进展",
         columns=("股东/实际控制人股份增持",)),
    Rule("buyback", "回购股份", +1, "minor", 2, r"回购.{0,4}(方案|股份|计划|报告书)",
         exclude=r"注销|进展|完成|实施结果|限制性", columns=("回购方案修订",)),
    Rule("incentive", "股权激励 / 员工持股", +1, "minor", 2, r"股权激励|员工持股|激励计划",
         exclude=r"回购注销|作废|名单|法律意见|核查|考核|自查|摘要|管理办法|意见|调整|延长|预留|归属|解锁|锁定期|授予|实施"),
    Rule("bonus_share", "高送转 / 转增", +1, "minor", 2, r"转增|送股|每10股送"),
    Rule("private_placement_ok", "定增获批 / 注册生效", +1, "minor", 2,
         r"(发行|定增).{0,10}(获得|获|同意).{0,6}(注册|批复|核准)", exclude=r"债|融资工具|票据"),
    Rule("subsidy", "获得政府补助", +1, "minor", 1, r"政府补助|获得补贴|获得.{0,4}补助"),

    # ---- 方向需要看正文 ----
    Rule("earnings_preview", "业绩预告（方向看正文）", 0, "notable", 3, r"业绩预告|业绩快报"),
    Rule("bankruptcy_restructure", "破产重整 / 预重整（方向看正文）", 0, "major", 5, r"重整", exclude=r"参与|入伙"),
    Rule("resume_trading", "复牌", 0, "minor", 1, r"复牌"),
)

# 纯价格报道（"XX 涨停"、"XX 大跌"）不是催化剂本身：只有没命中上面任何规则时才归到这里
_PRICE_ONLY = re.compile(r"涨停|跌停|大涨|大跌|拉升|跳水|异动|翻红|翻绿|领涨|领跌|龙虎榜|主力资金")

_FOLLOW_UP = re.compile(r"进展|第[一二三四五六七八九十\d]+次.{0,6}提示|持续|定期|实施情况")

_COMPILED = [
    (r, re.compile(r.pattern), re.compile(r.exclude) if r.exclude else None) for r in RULES
]
RULE_BY_TYPE = {r.type: r for r in RULES}


def classify(title: str, columns: Sequence[str] = ()) -> Dict[str, Any]:
    """按规则给一条消息定性。返回 type / label / direction / level / half_life。"""
    text = title or ""
    cols = set(columns or ())
    for rule, pattern, exclude in _COMPILED:
        if exclude is not None and exclude.search(text):
            continue
        if pattern.search(text) or (rule.columns and cols.intersection(rule.columns)):
            level, label = rule.level, rule.label
            # "……相关事项的进展公告""第八次风险提示"：事件早已公布，这里只是例行提醒，不能再当重大新消息
            if level in ("major", "notable") and _FOLLOW_UP.search(text):
                level, label = "minor", f"{rule.label}（后续进展）"
            return {
                "type": rule.type,
                "type_label": label,
                "direction": rule.direction,
                "level": level,
                "half_life": rule.half_life,
            }
    label = "价格异动报道" if _PRICE_ONLY.search(text) else "常规信息"
    return {"type": "other", "type_label": label, "direction": 0, "level": "noise", "half_life": 1}


# ---------------------------------------------------------------------------
# 交易日与时间衰减
# ---------------------------------------------------------------------------

TradingDayChecker = Callable[[date], Optional[bool]]


def _default_checker(day: date) -> Optional[bool]:
    try:
        from workbench_service import _default_trading_day_checker

        return _default_trading_day_checker(day)
    except Exception:
        return None


def is_trading_day(day: date, checker: Optional[TradingDayChecker] = None) -> bool:
    if day.weekday() >= 5:
        return False
    result = (checker or _default_checker)(day)
    return True if result is None else bool(result)  # 日历拿不到时按工作日算


def reaction_date(published: datetime) -> date:
    """消息第一次能被交易反应的日期：收盘（15:00）后发布的算到下一天。"""
    if published.tzinfo is None:
        published = published.replace(tzinfo=TZ)
    local = published.astimezone(TZ)
    return local.date() + timedelta(days=1) if local.hour >= 15 else local.date()


def sessions_elapsed(effective: date, today: date, checker: Optional[TradingDayChecker] = None) -> int:
    """
    从消息首个可交易日到今天已经过了几个交易日。
    -1 = 还没迎来第一个交易日（盘后 / 周末 / 长假期间发布，下个交易日才反应）；
     0 = 今天就是第一个反应日。
    """
    first = effective
    for _ in range(20):
        if is_trading_day(first, checker):
            break
        first += timedelta(days=1)
    if first > today:
        return -1
    count, d = 0, first + timedelta(days=1)
    while d <= today:
        if is_trading_day(d, checker):
            count += 1
        d += timedelta(days=1)
    return count


def decay_factor(elapsed: int, half_life: float) -> float:
    if elapsed <= 0:
        return 1.0
    return 0.5 ** (elapsed / max(half_life, 0.5))


# ---------------------------------------------------------------------------
# 打分
# ---------------------------------------------------------------------------

def score_event(event: Dict[str, Any], today: date, checker: Optional[TradingDayChecker] = None) -> Dict[str, Any]:
    """给已分类的消息补上时间衰减与分数贡献（原地返回新 dict）。"""
    effective = event.get("effective_date")
    if isinstance(effective, str):
        effective = date.fromisoformat(effective[:10])
    elapsed = sessions_elapsed(effective, today, checker) if effective else 0
    decay = decay_factor(elapsed, event.get("half_life", 1))
    base = LEVEL_POINTS.get(event.get("level"), 0) * SOURCE_WEIGHT.get(event.get("source"), 0.5)
    contribution = event.get("direction", 0) * base * decay
    return {
        **event,
        "effective_date": effective.isoformat() if effective else None,
        "sessions_elapsed": elapsed,
        "pending": elapsed < 0,
        "decay": round(decay, 3),
        "active": decay >= ACTIVE_DECAY,
        "contribution": round(contribution, 1),
        "level_label": LEVEL_LABEL.get(event.get("level"), ""),
        "source_label": SOURCE_LABEL.get(event.get("source"), ""),
    }


def aggregate(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """把已打分的消息汇总成一个 -100~100 的消息面分数 + 需要提醒的重大消息。"""
    by_type: Dict[str, List[float]] = {}
    for e in events:
        if e.get("contribution"):
            by_type.setdefault(e["type"], []).append(e["contribution"])
    type_totals = {}
    for t, values in by_type.items():
        values = sorted(values, key=abs, reverse=True)
        type_totals[t] = values[0] + SAME_TYPE_EXTRA * sum(values[1:])
    raw = sum(type_totals.values())
    score = round(100 * math.tanh(raw / SCORE_SCALE))

    alerts = [
        e for e in events
        if e.get("level") == "major" and e.get("active")
    ]
    # 方向待确认、但等级够高的消息也要提醒去看正文
    review = [
        e for e in events
        if e.get("direction") == 0 and e.get("level") in ("major", "notable") and e.get("active")
    ]
    if score >= 40:
        label, tone = "利好明显", "up"
    elif score >= 15:
        label, tone = "偏利好", "up"
    elif score <= -40:
        label, tone = "利空明显", "down"
    elif score <= -15:
        label, tone = "偏利空", "down"
    else:
        label, tone = "中性", "flat"

    top = sorted(type_totals.items(), key=lambda kv: abs(kv[1]), reverse=True)
    drivers = [
        {"type": t, "label": RULE_BY_TYPE[t].label if t in RULE_BY_TYPE else t, "points": round(v, 1)}
        for t, v in top[:3]
    ]
    return {
        "score": score,
        "raw": round(raw, 1),
        "label": label,
        "tone": tone,
        "drivers": drivers,
        "alerts": alerts,
        "review": review,
        "summary": _summary(score, label, alerts, review, drivers),
    }


def _summary(score, label, alerts, review, drivers) -> str:
    if alerts:
        first = alerts[0]
        side = "利好" if first["direction"] > 0 else "利空" if first["direction"] < 0 else "消息"
        when = "下个交易日首次反应" if first.get("pending") else (
            "今天首次反应" if first.get("sessions_elapsed") == 0 else f"已过 {first['sessions_elapsed']} 个交易日")
        more = f"等 {len(alerts)} 条" if len(alerts) > 1 else ""
        return f"有重大{side}：{first['type_label']}{more}（{when}），消息面 {score:+d}"
    if review:
        return f"有需要看正文判断方向的{review[0]['type_label']}，消息面 {score:+d}"
    if drivers and label != "中性":
        return f"消息面{label}（{score:+d}），主要来自{drivers[0]['label']}"
    if drivers:
        return f"消息面中性（{score:+d}），近期没有明显的利好或利空"
    return "近期没有值得注意的公告或新闻"


# ---------------------------------------------------------------------------
# 抓取
# ---------------------------------------------------------------------------

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
EM_ANN_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
EM_NEWS_URL = "https://search-api-web.eastmoney.com/search/jsonp"
CNINFO_SEARCH_URL = "https://www.cninfo.com.cn/new/information/topSearch/query"
CNINFO_ANN_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"


def _parse_dt(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):  # 毫秒时间戳
        return datetime.fromtimestamp(value / 1000, TZ)
    text = str(value).strip()[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=TZ)
        except ValueError:
            continue
    return None


def _strip_name_prefix(title: str) -> str:
    # 全市场公告标题形如"长安汽车:关于...的公告"
    return re.sub(r"^[^:：]{1,12}[:：]", "", title or "").strip()


_A_SHARE = re.compile(r"(00|30|60|68|43|83|87|88|92)\d{4}")  # 排除 B 股、可转债等


def notice_url(code: str, art_code: str) -> str:
    return f"https://data.eastmoney.com/notices/detail/{code}/{art_code}.html"


def parse_em_announcement(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    codes = item.get("codes") or []
    a_share = next((c for c in codes if _A_SHARE.fullmatch(str(c.get("stock_code", "")))), None)
    if not a_share:
        return None
    code = a_share["stock_code"]
    title = _strip_name_prefix(item.get("title_ch") or item.get("title") or "")
    columns = [c.get("column_name") for c in (item.get("columns") or []) if c.get("column_name")]
    published = _parse_dt(item.get("display_time")) or _parse_dt(item.get("notice_date"))
    notice_day = _parse_dt(item.get("notice_date"))
    effective = notice_day.date() if notice_day else (reaction_date(published) if published else None)
    if published and effective and reaction_date(published) > effective:
        effective = reaction_date(published)
    return {
        "id": item.get("art_code"),
        "source": "announcement",
        "code": code,
        "name": a_share.get("short_name") or "",
        "title": title,
        "columns": columns,
        "published_at": published.strftime("%Y-%m-%d %H:%M") if published else None,
        "effective_date": effective,
        "url": notice_url(code, item.get("art_code", "")),
        **classify(title, columns),
    }


class NewsFetcher:
    """所有外部请求集中在这里，测试时整个替换掉。"""

    def __init__(self, client: Optional[DataSourceClient] = None):
        self.client = client or DataSourceClient()
        self._org_ids: Dict[str, str] = {}

    # ---- 公告 ----
    def announcements(self, code: str, since: date) -> Tuple[List[Dict[str, Any]], str]:
        """返回 (近期公告, 股票简称)。简称从全部返回里取，即使近期没有公告也能拿到。"""
        try:
            return self._em_announcements(code, since)
        except Exception as exc:
            logger.info(f"[news] 东财公告失败 {code}，改用巨潮：{exc}")
            return self._cninfo_announcements(code, since)

    def _em_announcements(self, code: str, since: date) -> Tuple[List[Dict[str, Any]], str]:
        res = self.client.get("eastmoney_notice", EM_ANN_URL, headers=_UA, params={
            "page_size": 50, "page_index": 1, "ann_type": "A", "client_source": "web",
            "f_node": 0, "s_node": 0, "stock_list": code,
        })
        if not res.ok:
            raise RuntimeError(res.error)
        items = ((res.response.json() or {}).get("data") or {}).get("list") or []
        out, name = [], ""
        for item in items:
            ev = parse_em_announcement(item)
            if not ev:
                continue
            name = name or ev["name"]
            if ev["effective_date"] and ev["effective_date"] >= since:
                out.append(ev)
        return out, name

    def _cninfo_announcements(self, code: str, since: date) -> Tuple[List[Dict[str, Any]], str]:
        session = self.client.session
        org_id = self._org_ids.get(code)
        if not org_id:
            r = session.post(CNINFO_SEARCH_URL, data={"keyWord": code, "maxNum": 5}, headers=_UA, timeout=8)
            r.raise_for_status()
            match = next((x for x in r.json() if x.get("code") == code), None)
            if not match:
                raise RuntimeError("巨潮找不到该代码")
            org_id = self._org_ids[code] = match["orgId"]
            self._org_ids[f"{code}:name"] = match.get("zwjc") or ""
        column = "sse" if code.startswith(("6", "9")) else "bj" if code.startswith(("4", "8")) else "szse"
        r = session.post(CNINFO_ANN_URL, headers=_UA, timeout=10, data={
            "stock": f"{code},{org_id}", "tabName": "fulltext", "pageSize": 50, "pageNum": 1,
            "column": column, "category": "", "plate": "", "seDate": "", "searchkey": "",
            "secid": "", "sortName": "", "sortType": "", "isHLtitle": "true",
        })
        r.raise_for_status()
        out = []
        for a in r.json().get("announcements") or []:
            title = re.sub(r"<[^>]+>", "", a.get("announcementTitle") or "")
            day = _parse_dt(a.get("announcementTime"))
            if not day or day.date() < since:
                continue
            out.append({
                "id": str(a.get("announcementId")),
                "source": "announcement",
                "code": code,
                "name": a.get("secName") or "",
                "title": title,
                "columns": [],
                "published_at": day.strftime("%Y-%m-%d"),
                "effective_date": day.date(),
                "url": f"https://static.cninfo.com.cn/{a.get('adjunctUrl')}" if a.get("adjunctUrl") else None,
                **classify(title),
            })
        return out, self._org_ids.get(f"{code}:name", "")

    # ---- 新闻 ----
    def news(self, code: str, name: str, since: date) -> List[Dict[str, Any]]:
        param = {
            "uid": "", "keyword": code, "type": ["cmsArticleWebOld"], "client": "web",
            "clientType": "web", "clientVersion": "curr",
            "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "time", "pageIndex": 1,
                                           "pageSize": 30, "preTag": "", "postTag": ""}},
        }
        res = self.client.get("eastmoney", EM_NEWS_URL, headers=_UA, params={
            "cb": "cb", "param": json.dumps(param, ensure_ascii=False, separators=(",", ":")),
        })
        if not res.ok:
            raise RuntimeError(res.error)
        text = res.response.text
        body = json.loads(text[text.index("(") + 1: text.rindex(")")])
        result = body.get("result") or {}
        if "cmsArticleWebOld" not in result:  # 被风控时会返回一份与请求无关的默认结果
            raise RuntimeError("资讯接口返回了非预期内容")
        items = result.get("cmsArticleWebOld") or []
        out = []
        for it in items:
            title = re.sub(r"<[^>]+>", "", it.get("title") or "")
            # 只收"主角是这只股票"的稿件：名称出现在标题开头附近。
            # 否则"遭宁德时代等股东减持，湖南裕能……"这种会被错记到宁德时代头上。
            pos = title.find(name) if name else -1
            if pos < 0 or pos > NEWS_NAME_MAX_POS:
                continue
            published = _parse_dt(it.get("date"))
            if not published or published.date() < since:
                continue
            out.append({
                "id": it.get("code"),
                "source": "news",
                "code": code,
                "name": name,
                "title": title,
                "columns": [],
                "media": it.get("mediaName") or "",
                "published_at": published.strftime("%Y-%m-%d %H:%M"),
                "effective_date": reaction_date(published),
                "url": it.get("url"),
                **classify(title),
            })
        return out

    # ---- 全市场公告（雷达用）----
    def market_announcements(self, begin: date, end: date, max_pages: int = 30) -> Tuple[List[Dict[str, Any]], bool]:
        """返回 (公告列表, 是否完整)。页数到上限时 complete=False。"""
        out: List[Dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            res = self.client.get("eastmoney_notice", EM_ANN_URL, headers=_UA, params={
                "page_size": 100, "page_index": page, "ann_type": "SHA,CYB,SZA,BJA,KCB",
                "client_source": "web", "f_node": 0, "s_node": 0,
                "begin_time": begin.isoformat(), "end_time": end.isoformat(),
            })
            if not res.ok:
                if not out:
                    raise RuntimeError(res.error)
                return out, False
            data = (res.response.json() or {}).get("data") or {}
            items = data.get("list") or []
            for item in items:
                ev = parse_em_announcement(item)
                if ev:
                    out.append(ev)
            if len(items) < 100 or page * 100 >= int(data.get("total_hits") or 0):
                return out, True
        return out, False


# 东财公告接口单独限速（全市场雷达一次要翻几十页）
DataSourceClient.POLICIES.setdefault("eastmoney_notice", {
    "timeout": 10, "retries": 2, "backoff": 0.6, "min_interval": 0.3, "max_failures": 4, "cooldown": 30,
})


# ---------------------------------------------------------------------------
# 对外服务
# ---------------------------------------------------------------------------

def _dedupe(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for e in events:
        key = (e.get("source"), e.get("id") or e.get("title"))
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


class NewsCatalystService:
    def __init__(self, fetcher: Optional[NewsFetcher] = None, checker: Optional[TradingDayChecker] = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(TZ)):
        self.fetcher = fetcher or NewsFetcher()
        self.checker = checker
        self.clock = clock
        self._lock = threading.Lock()

    def stock(self, code: str, name: str = "") -> Dict[str, Any]:
        now = self.clock()
        today = now.date()
        sources: Dict[str, Dict[str, Any]] = {}
        events: List[Dict[str, Any]] = []

        try:
            anns, ann_name = self.fetcher.announcements(code, today - timedelta(days=ANN_LOOKBACK_DAYS))
            events += anns
            sources["announcement"] = {"ok": True, "count": len(anns)}
            name = name or ann_name
        except Exception as exc:
            logger.warning(f"[news] 公告获取失败 {code}: {exc}")
            sources["announcement"] = {"ok": False, "error": str(exc)[:120]}

        if name:
            try:
                news = self.fetcher.news(code, name, today - timedelta(days=NEWS_LOOKBACK_DAYS))
                events += news
                sources["news"] = {"ok": True, "count": len(news)}
            except Exception as exc:
                logger.warning(f"[news] 新闻获取失败 {code}: {exc}")
                sources["news"] = {"ok": False, "error": str(exc)[:120]}
        else:
            sources["news"] = {"ok": False, "error": "缺少股票名称，无法过滤新闻"}

        if not any(s.get("ok") for s in sources.values()):
            raise RuntimeError("公告和新闻都获取失败：" + "；".join(s.get("error", "") for s in sources.values()))

        scored = [score_event(e, today, self.checker) for e in _dedupe(events)]
        scored.sort(key=lambda e: (e.get("published_at") or "", e.get("effective_date") or ""), reverse=True)
        agg = aggregate(scored)
        agg["alerts"] = [_public(e) for e in agg["alerts"]]
        agg["review"] = [_public(e) for e in agg["review"]]
        return {
            "code": code,
            "name": name,
            **agg,
            "events": [_public(e) for e in scored],
            "sources": sources,
            "as_of": now.strftime("%Y-%m-%d %H:%M:%S"),
            "mode": "observe",
        }

    def radar(self) -> Dict[str, Any]:
        """
        全市场重大消息：还没被交易、或正在被交易的公告里，挑出重大 / 显著事件。

        公告的 notice_date 就是它第一个能被交易的日子（收盘后发布的记在下一个交易日），
        所以窗口从"今天（非交易日则为下个交易日）"开始；往后多看 12 天，覆盖长假期间发布、
        记在节后首日的公告。昨天盘中的公告已经交易过，不在雷达里。
        """
        now = self.clock()
        today = now.date()
        begin = today
        while not is_trading_day(begin, self.checker) and (begin - today).days < 15:
            begin += timedelta(days=1)
        end = begin + timedelta(days=12)
        items, complete = self.fetcher.market_announcements(today, end)
        grouped: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for e in _dedupe(items):
            if e["level"] not in ("major", "notable"):
                continue
            key = (e["code"], e["type"])
            if key in grouped:  # 同一家公司同一件事的多份文件合并成一条
                grouped[key]["related"] += 1
                continue
            grouped[key] = {**score_event(e, today, self.checker), "related": 0}
        scored = list(grouped.values())
        level_rank = {"major": 0, "notable": 1}
        scored.sort(key=lambda e: e.get("published_at") or "", reverse=True)  # 新的在前
        scored.sort(key=lambda e: level_rank.get(e["level"], 9))               # 再按等级（稳定排序）
        counts = {
            "major_up": sum(1 for e in scored if e["level"] == "major" and e["direction"] > 0),
            "major_down": sum(1 for e in scored if e["level"] == "major" and e["direction"] < 0),
            "notable": sum(1 for e in scored if e["level"] == "notable"),
            "scanned": len(items),
        }
        return {
            "events": [_public(e) for e in scored[:300]],
            "counts": counts,
            "window": {"begin": today.isoformat(), "reaction_day": begin.isoformat(), "end": end.isoformat()},
            "complete": complete,
            "as_of": now.strftime("%Y-%m-%d %H:%M:%S"),
        }


_PUBLIC_KEYS = (
    "id", "source", "source_label", "code", "name", "title", "media", "published_at", "effective_date",
    "url", "type", "type_label", "direction", "level", "level_label", "half_life",
    "sessions_elapsed", "pending", "decay", "active", "contribution", "related",
)


def _public(e: Dict[str, Any]) -> Dict[str, Any]:
    return {k: e.get(k) for k in _PUBLIC_KEYS if k in e}


__all__ = [
    "LEVEL_POINTS", "RULES", "SOURCE_WEIGHT", "NewsCatalystService", "NewsFetcher", "aggregate", "classify",
    "decay_factor", "reaction_date", "score_event", "sessions_elapsed",
]
