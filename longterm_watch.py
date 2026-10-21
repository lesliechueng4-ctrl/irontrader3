"""
长线观察：几个"风口"方向的研究结论、风停信号、龙头标的，以及同花顺分组导入。

研究数据放在仓库里的 data/longterm_watch.json（每月由定时任务按最新公开资料更新后提交），
这里负责读取、校验、按分组整理，以及给 A 股龙头配上实时行情（现价 / 涨跌幅 / 市盈率 / 总市值 / 年内涨幅）。

约定：
- 只给 A 股（sh / sz / bj）取行情；港股、美股、未上市一律显示"暂无"，不拿估算值凑数。
- 行情取不到时对应字段为 None，前端显示"暂无"。
- 纯函数（解析、计算、分组、导出文本）不访问网络，单元测试直接调用。
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from runtime_paths import application_resource_dir

A_MARKETS = ("sh", "sz", "bj")
LAMPS = ("green", "yellow", "red")
TENCENT_BATCH = 60  # 腾讯行情一次最多查几只（实测几十只没问题，留余量）


# ---------------------------------------------------------------------------
# 研究数据
# ---------------------------------------------------------------------------

def data_path() -> Path:
    return application_resource_dir() / "data" / "longterm_watch.json"


class WatchDataError(ValueError):
    """data/longterm_watch.json 结构不对（定时任务或手工编辑写坏了）。"""


def validate(doc: Dict[str, Any]) -> List[str]:
    """返回问题列表；空列表表示结构正确。CI 用它检查仓库里的数据文件。"""
    problems: List[str] = []
    if not isinstance(doc, dict):
        return ["顶层必须是对象"]
    for key in ("as_of", "takeaway", "disclaimer"):
        if not isinstance(doc.get(key), str) or not doc.get(key):
            problems.append(f"缺少 {key}")
    for key in ("directions", "groups", "leaders", "signals"):
        if not isinstance(doc.get(key), list):
            problems.append(f"{key} 必须是数组")
    if problems:
        return problems

    dir_ids = {d.get("id") for d in doc["directions"]}
    group_ids = {g.get("id") for g in doc["groups"]}
    for g in doc["groups"]:
        if g.get("dir") not in dir_ids:
            problems.append(f"分组 {g.get('id')} 的方向 {g.get('dir')} 不存在")

    seen = set()
    for r in doc["leaders"]:
        rid = r.get("id")
        if rid in seen:
            problems.append(f"龙头 id 重复：{rid}")
        seen.add(rid)
        if r.get("dir") not in dir_ids:
            problems.append(f"龙头 {rid} 的方向 {r.get('dir')} 不存在")
        market, code = r.get("market"), r.get("code")
        if market in A_MARKETS:
            if not (isinstance(code, str) and len(code) == 6 and code.isdigit()):
                problems.append(f"龙头 {rid} 的 A 股代码不是 6 位数字：{code!r}")
        elif market == "hk":
            if not (isinstance(code, str) and len(code) == 5 and code.isdigit()):
                problems.append(f"龙头 {rid} 的港股代码不是 5 位数字：{code!r}")
        elif market == "us":
            if not (isinstance(code, str) and code.isalpha()):
                problems.append(f"龙头 {rid} 的美股代码不对：{code!r}")
        elif market != "unlisted":
            problems.append(f"龙头 {rid} 的市场未知：{market!r}")
        for gid in r.get("groups") or []:
            if gid not in group_ids:
                problems.append(f"龙头 {rid} 的分组 {gid} 不存在")
        if not r.get("sources"):
            problems.append(f"龙头 {rid} 没有来源链接")

    seen = set()
    for s in doc["signals"]:
        sid = s.get("id")
        if sid in seen:
            problems.append(f"信号 id 重复：{sid}")
        seen.add(sid)
        if s.get("dir") not in dir_ids:
            problems.append(f"信号 {sid} 的方向 {s.get('dir')} 不存在")
        if s.get("lamp") not in LAMPS:
            problems.append(f"信号 {sid} 的灯只能是 green / yellow / red：{s.get('lamp')!r}")
        if not s.get("sources"):
            problems.append(f"信号 {sid} 没有来源链接")
    return problems


def load(path: Optional[Path] = None) -> Dict[str, Any]:
    path = path or data_path()
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    problems = validate(doc)
    if problems:
        raise WatchDataError("；".join(problems[:5]))
    return doc


def build_groups(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """同花顺分组：A 股进导入清单（codes），港股 / 美股列在 manual 里提示手动添加。"""
    out = []
    for g in doc["groups"]:
        members = [r for r in doc["leaders"] if g["id"] in (r.get("groups") or [])]
        importable = [r for r in members if r.get("market") in A_MARKETS]
        manual = [r for r in members if r.get("market") in ("hk", "us")]
        out.append({
            **g,
            "codes": [r["code"] for r in importable],
            "stocks": [{"code": r["code"], "name": r["name"]} for r in importable],
            "manual": [{"code": r["code"], "name": r["name"], "market": r["market"]} for r in manual],
        })
    return out


def ths_import_text(codes: Iterable[str]) -> str:
    """同花顺"从文本中导入"：一行一个 6 位代码，Windows 换行。只有数字，不受文件编码影响。"""
    uniq: List[str] = []
    for c in codes:
        if c not in uniq:
            uniq.append(c)
    return "".join(f"{c}\r\n" for c in uniq)


def a_share_codes(doc: Dict[str, Any]) -> List[str]:
    codes: List[str] = []
    for r in doc["leaders"]:
        if r.get("market") in A_MARKETS and r["code"] not in codes:
            codes.append(r["code"])
    return codes


# ---------------------------------------------------------------------------
# 行情
# ---------------------------------------------------------------------------

def market_of(code: str) -> str:
    if code.startswith(("6", "9")):
        return "sh"
    if code.startswith(("4", "8")):
        return "bj"
    return "sz"


def _num(text: str) -> Optional[float]:
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value


def parse_tencent_quotes(text: str) -> Dict[str, Dict[str, Any]]:
    """
    解析腾讯 qt.gtimg.cn 批量行情（v_sh600276="1~恒瑞医药~600276~价格~昨收~今开~...";）。
    字段位置：1 名称、2 代码、3 现价、4 昨收、30 时间、32 涨跌幅%、39 市盈率(TTM)、45 总市值(亿)。
    停牌或现价为 0 时现价、涨跌幅记为 None。
    """
    quotes: Dict[str, Dict[str, Any]] = {}
    for line in text.split(";"):
        if '="' not in line:
            continue
        body = line.split('="', 1)[1].rsplit('"', 1)[0]
        parts = body.split("~")
        if len(parts) < 46:
            continue
        code = parts[2].strip()
        if not (len(code) == 6 and code.isdigit()):
            continue
        price = _num(parts[3])
        prev = _num(parts[4])
        trading = bool(price and price > 0)
        pe = _num(parts[39])
        mv = _num(parts[45])
        quotes[code] = {
            "name": parts[1].strip(),
            "price": price if trading else None,
            "prev_close": prev if prev and prev > 0 else None,
            "change_pct": _num(parts[32]) if trading else None,
            # 亏损公司市盈率为负或 0，原样给出；取不到才是 None
            "pe_ttm": pe if pe is not None and pe != 0 else None,
            "total_mv_yi": mv if mv and mv > 0 else None,
            "quote_time": parts[30].strip() or None,
        }
    return quotes


def ytd_change(bars: List[Dict[str, Any]], price: Optional[float], today: date) -> Dict[str, Any]:
    """
    年内涨幅 = 现价 / 去年最后一个交易日收盘价 - 1（前复权日 K）。
    今年才上市的票没有去年收盘价，返回 None 并说明原因，不拿上市首日价冒充。
    """
    if not bars:
        return {"ytd_pct": None, "ytd_note": "暂无日K"}
    year_start = date(today.year, 1, 1).isoformat()
    if str(bars[0]["date"]) >= year_start:
        return {"ytd_pct": None, "ytd_note": "今年上市"}
    base = None
    for bar in bars:
        if str(bar["date"]) < year_start:
            base = bar["close"]
        else:
            break
    last = price if price and price > 0 else bars[-1]["close"]
    if not base or base <= 0 or not last:
        return {"ytd_pct": None, "ytd_note": "暂无日K"}
    return {"ytd_pct": round((last / base - 1) * 100, 2), "ytd_note": None}


def fetch_tencent_quotes(client, codes: List[str]) -> Dict[str, Dict[str, Any]]:
    """批量取腾讯行情；某一批失败不影响其他批，失败的票不出现在结果里。"""
    quotes: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(codes), TENCENT_BATCH):
        batch = codes[i:i + TENCENT_BATCH]
        q = ",".join(f"{market_of(c)}{c}" for c in batch)
        res = client.get("tencent", f"http://qt.gtimg.cn/q={q}",
                         headers={"User-Agent": "Mozilla/5.0", "Referer": "http://gu.qq.com"})
        if not res.ok:
            continue
        quotes.update(parse_tencent_quotes(res.response.content.decode("gbk", errors="ignore")))
    return quotes


def fetch_year_bars(bars_fn: Callable[[str], List[Dict[str, Any]]], codes: List[str],
                    workers: int = 6) -> Dict[str, List[Dict[str, Any]]]:
    """并行取日 K（只用来找去年收盘价）。单票失败记空列表，不中断其他票。"""

    def one(code: str):
        try:
            return code, bars_fn(code)
        except Exception:
            return code, []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(one, codes))


def merge_quotes(codes: List[str], quotes: Dict[str, Dict[str, Any]],
                 bars: Dict[str, List[Dict[str, Any]]], today: date) -> Dict[str, Dict[str, Any]]:
    """每只 A 股一条：行情字段 + 年内涨幅；取不到的字段为 None。"""
    out: Dict[str, Dict[str, Any]] = {}
    for code in codes:
        q = quotes.get(code)
        row: Dict[str, Any] = {
            "price": None, "change_pct": None, "pe_ttm": None, "total_mv_yi": None,
            "quote_time": None, "ytd_pct": None, "ytd_note": None, "available": False,
        }
        if q:
            row.update({k: q[k] for k in ("price", "change_pct", "pe_ttm", "total_mv_yi", "quote_time")})
            row["available"] = q["price"] is not None or q["prev_close"] is not None
            ref_price = q["price"] or q["prev_close"]
        else:
            ref_price = None
        if code in bars:
            row.update(ytd_change(bars[code], ref_price, today))
        out[code] = row
    return out


__all__ = [
    "A_MARKETS", "WatchDataError", "a_share_codes", "build_groups", "data_path", "fetch_tencent_quotes",
    "fetch_year_bars", "load", "market_of", "merge_quotes", "parse_tencent_quotes", "ths_import_text",
    "validate", "ytd_change",
]
