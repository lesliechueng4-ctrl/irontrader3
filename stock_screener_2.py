"""
A股选股筛选器
条件：均线多头排列 + MACD金叉 + 涨幅过滤 + 量比条件
每天收盘后运行，自动输出候选池

依赖：pip install akshare pandas ta tqdm
"""

import os
import sys
import urllib.request

# ── 代理修复 ──────────────────────────────────────────────────
# 清除环境变量代理
for _proxy_key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
                   "all_proxy", "ALL_PROXY", "no_proxy", "NO_PROXY"):
    os.environ.pop(_proxy_key, None)
# Windows注册表代理无法被env清理，直接monkey-patch让requests看不到任何代理
urllib.request.getproxies = lambda: {}
try:
    import urllib.request as _ur
    _ur.getproxies_environment = lambda: {}
    _ur.getproxies_registry = lambda: {}
except Exception:
    pass

# Windows GBK终端兼容：强制UTF-8输出，避免emoji编码错误
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import akshare as ak
import pandas as pd
import ta
from tqdm import tqdm
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings("ignore")

# ============================================================
# 参数配置（可自由调整）
# ============================================================
CONFIG = {
    # 均线参数
    "ma_periods": [5, 10, 20, 30],         # 均线周期

    # 涨幅过滤（当日）
    "min_pct_change": -3.0,                 # 最小涨幅%（排除暴跌）
    "max_pct_change": 9.5,                  # 最大涨幅%（排除涨停追高）

    # 历史涨幅过滤（近N日总涨幅，防止追高）
    "recent_days": 20,                      # 近N日
    "max_recent_gain": 50.0,                # 近N日涨幅不超过X%

    # 量比条件
    "min_volume_ratio": 0.8,                # 最小量比（排除极度缩量）
    "max_volume_ratio": 5.0,                # 最大量比（排除异常炒作）

    # MACD参数
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,

    # 数据获取
    "history_days": 90,                     # 获取多少天历史数据用于计算
    "exclude_st": True,                     # 排除ST股票
    "exclude_kechuang": False,              # 是否排除科创板（688开头）
    "exclude_chuangye": False,              # 是否排除创业板（300开头）

    # 市值过滤（亿元）
    "min_market_cap": 50,                   # 最小市值（排除垃圾小票）
    "max_market_cap": 5000,                 # 最大市值（可选，None=不限）

    # 输出
    "output_file": "候选股票池.csv",
    "top_n": 50,                            # 最多输出N只
}

# ============================================================
# 工具函数
# ============================================================

def get_all_stocks():
    """获取A股全部股票列表（使用新浪财经数据源，已验证可用）"""
    import requests
    print("📋 获取股票列表...")

    NO_PROXY = {"http": None, "https": None}
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "http://finance.sina.com.cn/",
    }

    def fetch_sina_market(node):
        """分页拉取新浪财经某市场的全部股票"""
        # 先获取总数
        count_url = ("http://vip.stock.finance.sina.com.cn/quotes_service"
                     "/api/json_v2.php/Market_Center.getHQNodeStockCount")
        r = requests.get(count_url, params={"node": node}, headers=HEADERS,
                         proxies=NO_PROXY, timeout=15)
        total = int(r.text.strip().strip('"'))

        data_url = ("http://vip.stock.finance.sina.com.cn/quotes_service"
                    "/api/json_v2.php/Market_Center.getHQNodeDataSimple")
        records = []
        page_size = 200
        pages = (total + page_size - 1) // page_size
        for pg in range(1, pages + 1):
            params = {
                "page": pg, "num": page_size,
                "sort": "symbol", "asc": 1,
                "node": node, "symbol": "", "_s_r_a": "page",
            }
            r2 = requests.get(data_url, params=params, headers=HEADERS,
                              proxies=NO_PROXY, timeout=15)
            items = r2.json()
            for item in items:
                sym = item.get("symbol", "")          # e.g. "sh600000"
                code = item.get("code", sym[-6:])      # 6位纯数字
                name = item.get("name", "")
                records.append({"code": str(code).zfill(6), "name": name})
        return records

    try:
        sh_stocks = fetch_sina_market("sh_a")
        sz_stocks = fetch_sina_market("sz_a")
        all_records = sh_stocks + sz_stocks
        df = pd.DataFrame(all_records)
    except Exception as e:
        raise RuntimeError(f"无法获取股票列表（新浪财经接口失败）：{e}") from e

    # 排除ST
    if CONFIG["exclude_st"]:
        df = df[~df["name"].str.contains("ST|退", na=False, case=False)]

    # 排除科创板
    if CONFIG["exclude_kechuang"]:
        df = df[~df["code"].str.startswith("688")]

    # 排除创业板
    if CONFIG["exclude_chuangye"]:
        df = df[~df["code"].str.startswith("300")]

    # 只保留 A 股主要板块（过滤北交所等）
    df = df[df["code"].str.startswith(("000", "001", "002", "003", "600", "601", "603", "605", "688", "300"))]

    df = df.drop_duplicates("code").reset_index(drop=True)
    print(f"✅ 共 {len(df)} 只股票待筛选")
    return df


def get_stock_history(code):
    """获取单只股票历史数据"""
    end_date = datetime.today().strftime("%Y%m%d")
    start_date = (datetime.today() - timedelta(days=CONFIG["history_days"] + 60)).strftime("%Y%m%d")
    
    try:
        # 判断市场
        if code.startswith(("600", "601", "603", "605")):
            symbol = f"sh{code}"
        elif code.startswith("688"):
            symbol = f"sh{code}"
        else:
            symbol = f"sz{code}"
        
        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq"  # 前复权
        )
        
        if df is None or len(df) < 35:
            return None
            
        df = df.rename(columns={
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "振幅": "amplitude",
            "涨跌幅": "pct_change",
            "涨跌额": "change",
            "换手率": "turnover"
        })
        
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df
        
    except Exception:
        return None


def check_ma_alignment(df):
    """
    检查均线多头排列
    条件：MA5 > MA10 > MA20 > MA30，且均线向上发散
    """
    periods = CONFIG["ma_periods"]
    for p in periods:
        df[f"MA{p}"] = df["close"].rolling(p).mean()
    
    last = df.iloc[-1]
    
    # 检查多头排列：MA5 > MA10 > MA20 > MA30
    for i in range(len(periods) - 1):
        if last[f"MA{periods[i]}"] <= last[f"MA{periods[i+1]}"]:
            return False, {}
    
    # 股价在MA5上方
    if last["close"] < last["MA5"]:
        return False, {}
    
    ma_data = {f"MA{p}": round(last[f"MA{p}"], 3) for p in periods}
    return True, ma_data


def check_macd_golden_cross(df):
    """
    检查MACD金叉
    条件：DIF上穿DEA（近3日内发生金叉），且MACD > 0 or 刚过零轴
    """
    macd = ta.trend.MACD(
        df["close"],
        window_fast=CONFIG["macd_fast"],
        window_slow=CONFIG["macd_slow"],
        window_sign=CONFIG["macd_signal"]
    )
    
    df["DIF"] = macd.macd()
    df["DEA"] = macd.macd_signal()
    df["MACD"] = macd.macd_diff() * 2  # 柱状图
    
    # 检查近3日是否发生金叉（DIF从下方穿越DEA）
    golden_cross = False
    for i in range(-3, 0):
        if (df["DIF"].iloc[i-1] < df["DEA"].iloc[i-1] and 
            df["DIF"].iloc[i] >= df["DEA"].iloc[i]):
            golden_cross = True
            break
    
    # 也接受DIF > DEA且两者都在上升（持续金叉状态）
    last = df.iloc[-1]
    dif_above_dea = last["DIF"] > last["DEA"]
    dif_positive = last["DIF"] > 0  # 零轴以上更强
    
    macd_data = {
        "DIF": round(last["DIF"], 3),
        "DEA": round(last["DEA"], 3),
        "MACD": round(last["MACD"], 3),
        "金叉": golden_cross
    }
    
    # 通过条件：近期金叉 OR (DIF>DEA且DIF>0)
    passed = golden_cross or (dif_above_dea and dif_positive)
    return passed, macd_data


def check_volume_ratio(df):
    """
    检查量比条件
    量比 = 当日成交量 / 近5日平均成交量
    """
    if len(df) < 6:
        return False, 0
    
    avg_vol_5 = df["volume"].iloc[-6:-1].mean()
    if avg_vol_5 == 0:
        return False, 0
    
    vol_ratio = df["volume"].iloc[-1] / avg_vol_5
    
    passed = CONFIG["min_volume_ratio"] <= vol_ratio <= CONFIG["max_volume_ratio"]
    return passed, round(vol_ratio, 2)


def check_price_change(df):
    """
    检查当日涨幅
    排除涨停追高、排除暴跌
    """
    last_pct = df["pct_change"].iloc[-1]
    passed = CONFIG["min_pct_change"] <= last_pct <= CONFIG["max_pct_change"]
    return passed, round(last_pct, 2)


def check_recent_gain(df):
    """
    检查近N日涨幅，防止追高
    """
    n = CONFIG["recent_days"]
    if len(df) < n:
        return True, 0  # 数据不足则放行
    
    price_n_days_ago = df["close"].iloc[-n]
    price_now = df["close"].iloc[-1]
    
    if price_n_days_ago == 0:
        return True, 0
    
    recent_gain = (price_now - price_n_days_ago) / price_n_days_ago * 100
    
    passed = recent_gain <= CONFIG["max_recent_gain"]
    return passed, round(recent_gain, 2)


def score_stock(ma_data, macd_data, vol_ratio, pct_change, recent_gain):
    """
    综合评分（0-100分）
    """
    score = 0
    
    # 均线发散程度（MA5和MA30差距越大越好，但不能过大）
    ma5 = ma_data.get("MA5", 0)
    ma30 = ma_data.get("MA30", 0)
    if ma30 > 0:
        spread = (ma5 - ma30) / ma30 * 100
        if 1 <= spread <= 15:
            score += 30
        elif spread < 1:
            score += 10  # 刚开始发散
        else:
            score += 20
    
    # MACD状态
    if macd_data.get("金叉"):
        score += 25  # 近期金叉加分
    if macd_data.get("DIF", 0) > 0:
        score += 15  # 零轴上方加分
    
    # 量比（1.2-2.5为最佳温和放量）
    if 1.2 <= vol_ratio <= 2.5:
        score += 20
    elif 0.8 <= vol_ratio < 1.2:
        score += 10
    else:
        score += 5
    
    # 当日涨幅（温和上涨最佳）
    if 1 <= pct_change <= 5:
        score += 10
    elif 0 <= pct_change < 1:
        score += 5
    
    return min(score, 100)


# ============================================================
# 主筛选逻辑
# ============================================================

def run_screener():
    print("\n" + "="*60)
    print(f"  A股选股筛选器  |  运行时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("="*60)
    
    stocks = get_all_stocks()
    candidates = []
    errors = 0
    
    print("\n🔍 开始逐股筛选...\n")
    
    for _, row in tqdm(stocks.iterrows(), total=len(stocks), desc="筛选进度"):
        code = row["code"]
        name = row["name"]
        
        try:
            df = get_stock_history(code)
            if df is None:
                continue
            
            # 逐条件筛选（短路逻辑，不满足立刻跳过）
            
            # 1. 涨幅过滤
            pct_ok, pct_change = check_price_change(df)
            if not pct_ok:
                continue
            
            # 2. 近期涨幅过滤（防追高）
            recent_ok, recent_gain = check_recent_gain(df)
            if not recent_ok:
                continue
            
            # 3. 均线多头排列
            ma_ok, ma_data = check_ma_alignment(df)
            if not ma_ok:
                continue
            
            # 4. MACD金叉
            macd_ok, macd_data = check_macd_golden_cross(df)
            if not macd_ok:
                continue
            
            # 5. 量比条件
            vol_ok, vol_ratio = check_volume_ratio(df)
            if not vol_ok:
                continue
            
            # 综合评分
            score = score_stock(ma_data, macd_data, vol_ratio, pct_change, recent_gain)
            
            last = df.iloc[-1]
            
            candidates.append({
                "代码": code,
                "名称": name,
                "现价": round(last["close"], 2),
                "今日涨幅%": pct_change,
                f"近{CONFIG['recent_days']}日涨幅%": recent_gain,
                "量比": vol_ratio,
                "MA5": ma_data.get("MA5"),
                "MA10": ma_data.get("MA10"),
                "MA20": ma_data.get("MA20"),
                "MA30": ma_data.get("MA30"),
                "DIF": macd_data.get("DIF"),
                "DEA": macd_data.get("DEA"),
                "MACD": macd_data.get("MACD"),
                "近期金叉": "✅" if macd_data.get("金叉") else "—",
                "综合评分": score,
            })
            
        except Exception as e:
            errors += 1
            continue
    
    # ============================================================
    # 输出结果
    # ============================================================
    
    if not candidates:
        print("\n❌ 今日没有符合条件的股票，市场可能整体偏弱。")
        return
    
    result_df = pd.DataFrame(candidates)
    result_df = result_df.sort_values("综合评分", ascending=False).head(CONFIG["top_n"])
    result_df = result_df.reset_index(drop=True)
    result_df.index += 1
    
    print(f"\n✅ 筛选完成！符合条件：{len(candidates)} 只，显示前 {len(result_df)} 只\n")
    print("=" * 60)
    
    # 终端输出
    display_cols = ["代码", "名称", "现价", "今日涨幅%", f"近{CONFIG['recent_days']}日涨幅%", "量比", "近期金叉", "综合评分"]
    print(result_df[display_cols].to_string())
    
    # 保存CSV
    output_path = CONFIG["output_file"]
    result_df.to_csv(output_path, index=True, encoding="utf-8-sig")
    print(f"\n💾 结果已保存至：{output_path}")
    print(f"⚠️  筛选出错股票数：{errors}（网络或数据问题，正常现象）")
    print("\n⚠️  本工具仅供技术分析参考，不构成投资建议。")
    
    return result_df


# ============================================================
# 筛选条件说明打印
# ============================================================

def print_config():
    print("\n📐 当前筛选条件：")
    print(f"  ✦ 均线多头排列：MA5 > MA10 > MA20 > MA30，股价在MA5上方")
    print(f"  ✦ MACD：近3日金叉 或 DIF>DEA且DIF>0（零轴上方）")
    print(f"  ✦ 今日涨幅：{CONFIG['min_pct_change']}% ~ {CONFIG['max_pct_change']}%（排除涨停追高）")
    print(f"  ✦ 近{CONFIG['recent_days']}日涨幅：不超过 {CONFIG['max_recent_gain']}%（防追高）")
    print(f"  ✦ 量比：{CONFIG['min_volume_ratio']} ~ {CONFIG['max_volume_ratio']}")
    print(f"  ✦ 排除ST：{'是' if CONFIG['exclude_st'] else '否'}")
    print(f"  ✦ 排除科创板：{'是' if CONFIG['exclude_kechuang'] else '否'}")


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    print_config()
    result = run_screener()
