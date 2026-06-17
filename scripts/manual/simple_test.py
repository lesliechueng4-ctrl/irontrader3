# -*- coding: utf-8 -*-
"""Quick manual check that DataFetcher can load the limit-up pool."""
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main():
    print("Testing DataFetcher...")
    print("=" * 60)

    try:
        from data_fetcher import DataFetcher
        print("[OK] DataFetcher imported successfully")

        fetcher = DataFetcher()
        print("[OK] DataFetcher initialized")

        print("\n[1] Testing get_limit_up_pool()...")
        pool = fetcher.get_limit_up_pool()
    except ImportError as exc:
        print(f"[FAIL] Import failed: {exc}")
        return 1
    except Exception as exc:
        print(f"[FAIL] Error: {exc}")
        import traceback

        traceback.print_exc()
        return 1

    if pool is None:
        print("[FAIL] pool is None")
        return 1

    if isinstance(pool, list):
        print(f"[OK] Got {len(pool)} limit-up stocks")
        for index, stock in enumerate(pool[:5], 1):
            print(f"\n{index}. {stock.get('code')} {stock.get('name')}")
            print(f"   Seal: {stock.get('seal_amount', 0):,.0f}")
            print(f"   Count: {stock.get('limit_count', 0)}")
            print(f"   Sector: {stock.get('sector', 'Unknown')}")

        print("\n[2] Searching for saltlake-related names in pool...")
        matches = [stock for stock in pool if "盐湖" in stock.get("name", "")]
        if matches:
            print(f"[OK] Found {len(matches)} matching stocks:")
            for index, stock in enumerate(matches, 1):
                print(f"{index}. {stock.get('code')} {stock.get('name')}")
        else:
            print("[INFO] No saltlake-related stock names found")
    else:
        print(f"[INFO] Got {pool.shape[0]} stocks (DataFrame)")
        print(pool.head().to_string())

    print("\n" + "=" * 60)
    print("Test complete")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
