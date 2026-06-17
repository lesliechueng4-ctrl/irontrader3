# -*- coding: utf-8 -*-
"""Manual smoke test for direct market data sources."""
import time

import requests


def fetch_sina(symbol):
    url = f"http://hq.sinajs.cn/list={symbol}"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "http://finance.sina.com.cn",
    }

    started = time.time()
    response = requests.get(url, headers=headers, timeout=5, proxies={"http": None, "https": None})
    elapsed = time.time() - started

    print(f"[sina] HTTP {response.status_code} in {elapsed:.2f}s")
    if response.status_code != 200:
        return None

    text = response.text.strip()
    if "=" not in text:
        return None

    payload = text.split("=", 1)[1].strip().rstrip(";").strip('"')
    parts = payload.split(",")
    if len(parts) < 4:
        return None

    try:
        name = parts[0]
        current = float(parts[3])
        previous_close = float(parts[2])
    except ValueError:
        return None

    change_pct = ((current - previous_close) / previous_close * 100) if previous_close else 0
    return {
        "source": "sina",
        "name": name,
        "current": current,
        "change_pct": change_pct,
    }


def fetch_eastmoney(secid):
    url = "http://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "fields": "f58,f43,f169,f170,f60",
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "http://quote.eastmoney.com",
    }

    started = time.time()
    response = requests.get(
        url,
        params=params,
        headers=headers,
        timeout=5,
        proxies={"http": None, "https": None},
    )
    elapsed = time.time() - started

    print(f"[eastmoney] HTTP {response.status_code} in {elapsed:.2f}s")
    if response.status_code != 200:
        return None

    data = response.json().get("data")
    if not data:
        return None

    return {
        "source": "eastmoney",
        "name": data.get("f58"),
        "current": data.get("f43"),
        "change_pct": data.get("f170"),
    }


def main():
    print("=" * 60)
    print("Data source manual smoke test")
    print("=" * 60)

    checks = [
        fetch_sina("sh000001"),
        fetch_eastmoney("1.000001"),
    ]
    results = [item for item in checks if item]

    print("\nSummary")
    print("-" * 60)
    for result in results:
        print(
            f"[OK] {result['source']}: {result.get('name')} "
            f"current={result.get('current')} change={result.get('change_pct')}"
        )

    if not results:
        print("[WARN] No direct data source returned parseable data")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
