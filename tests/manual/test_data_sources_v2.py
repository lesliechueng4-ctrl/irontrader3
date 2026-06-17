# -*- coding: utf-8 -*-
"""Manual smoke test for AKShare and project data source integration."""
import os
import time

import requests


def disable_proxy_env():
    proxy_vars = [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "NO_PROXY",
        "no_proxy",
        "ALL_PROXY",
        "all_proxy",
    ]
    for name in proxy_vars:
        os.environ.pop(name, None)
    os.environ["NO_PROXY"] = "*"


def check_akshare():
    print("\n[1] AKShare")
    try:
        import akshare as ak

        spot = ak.stock_zh_a_spot_em()
        print(f"[OK] stock_zh_a_spot_em rows={len(spot)}")

        history = ak.stock_zh_a_hist(symbol="sz002922", period="daily", adjust="qfq")
        print(f"[OK] stock_zh_a_hist rows={len(history)}")
        return True
    except Exception as exc:
        print(f"[FAIL] AKShare check failed: {exc}")
        return False


def check_sina():
    print("\n[2] Sina quote")
    url = "http://hq.sinajs.cn/list=sh000001"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "http://finance.sina.com.cn",
    }
    try:
        started = time.time()
        response = requests.get(url, headers=headers, timeout=5, proxies={"http": None, "https": None})
        elapsed = time.time() - started
        print(f"[OK] HTTP {response.status_code} in {elapsed:.2f}s")
        return response.status_code == 200 and "=" in response.text
    except Exception as exc:
        print(f"[FAIL] Sina check failed: {exc}")
        return False


def check_data_fetcher():
    print("\n[3] DataFetcher")
    try:
        from data_fetcher import DataFetcher

        fetcher = DataFetcher()
        pool = fetcher.get_limit_up_pool()
        if pool is None:
            print("[WARN] get_limit_up_pool returned None")
            return False
        if isinstance(pool, list):
            print(f"[OK] get_limit_up_pool list rows={len(pool)}")
        elif hasattr(pool, "shape"):
            print(f"[OK] get_limit_up_pool DataFrame shape={pool.shape}")
        else:
            print(f"[WARN] unexpected return type={type(pool)}")
        return True
    except Exception as exc:
        print(f"[FAIL] DataFetcher check failed: {exc}")
        return False


def main():
    print("=" * 60)
    print("Data source integration manual smoke test")
    print("=" * 60)

    disable_proxy_env()

    checks = [
        check_akshare(),
        check_sina(),
        check_data_fetcher(),
    ]
    ok_count = sum(1 for item in checks if item)

    print("\nSummary")
    print("-" * 60)
    print(f"{ok_count}/{len(checks)} checks passed")
    return 0 if ok_count else 1


if __name__ == "__main__":
    raise SystemExit(main())
