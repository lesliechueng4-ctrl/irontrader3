# -*- coding: utf-8 -*-
"""Manual DataFetcher smoke test.

This script may touch live/cache-backed data sources, so it belongs in
tests/manual instead of the default unit suite.
"""
import sys


def main():
    print("=" * 60)
    print("DataFetcher manual smoke test")
    print("=" * 60)

    print("\n[1] Importing DataFetcher...")
    try:
        from data_fetcher import DataFetcher
        print("[OK] DataFetcher imported")
    except Exception as exc:
        print(f"[FAIL] Import failed: {exc}")
        return 1

    print("\n[2] Initializing DataFetcher...")
    try:
        fetcher = DataFetcher()
        print("[OK] DataFetcher initialized")
    except Exception as exc:
        print(f"[FAIL] Initialization failed: {exc}")
        return 1

    print("\n[3] Checking expected methods...")
    expected_methods = [
        "get_index_realtime",
        "get_limit_up_pool",
        "get_stock_history",
        "get_market_sentiment",
    ]
    for name in expected_methods:
        status = "OK" if hasattr(fetcher, name) else "MISSING"
        print(f"[{status}] {name}")

    print("\n[4] Calling get_limit_up_pool()...")
    try:
        result = fetcher.get_limit_up_pool()
    except Exception as exc:
        print(f"[FAIL] get_limit_up_pool failed: {exc}")
        return 1

    if result is None:
        print("[WARN] get_limit_up_pool returned None")
    elif isinstance(result, list):
        print(f"[OK] Returned list with {len(result)} rows")
        if result:
            print("First row:")
            for key, value in result[0].items():
                print(f"  {key}: {value}")
    elif hasattr(result, "shape"):
        print(f"[OK] Returned DataFrame with shape {result.shape}")
        print(result.head().to_string())
    else:
        print(f"[WARN] Unexpected result type: {type(result)}")

    print("\nDone")
    return 0


if __name__ == "__main__":
    sys.exit(main())
