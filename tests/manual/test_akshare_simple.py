"""Manual AKShare smoke test.

This script calls live AKShare endpoints, so keep it in tests/manual rather
than the default unit-test suite.
"""
import sys


def main():
    print("=" * 60)
    print("AKShare manual smoke test")
    print("=" * 60)

    print("\n[1] Importing AKShare...")
    try:
        import akshare
        print("[OK] AKShare imported")
    except Exception as exc:
        print(f"[FAIL] AKShare import failed: {exc}")
        return 1

    print("\n[2] Fetching A-share spot data...")
    try:
        spot = akshare.stock_zh_a_spot_em()
        print(f"[OK] Got {len(spot)} rows")
        if len(spot) > 0:
            print("Top 3:")
            for _, row in spot.head(3).iterrows():
                print(f"  {row.get('代码')} {row.get('名称')} price={row.get('最新价')}")
    except Exception as exc:
        print(f"[FAIL] Spot fetch failed: {exc}")
        return 1

    print("\n[3] Searching for 002922...")
    try:
        by_code = spot[spot["代码"].astype(str) == "002922"]
        if len(by_code) > 0:
            stock = by_code.iloc[0]
            print(f"[OK] Found 002922: {stock.get('名称')} price={stock.get('最新价')}")
        else:
            print("[WARN] 002922 not found in spot data")
    except Exception as exc:
        print(f"[FAIL] Search failed: {exc}")

    print("\n[4] Fetching 002922 historical data...")
    try:
        history = akshare.stock_zh_a_hist(symbol="sz002922", period="daily", adjust="qfq")
        print(f"[OK] Got {len(history)} history rows")
        if len(history) > 0:
            print(history.tail(5).to_string(index=False))
    except Exception as exc:
        print(f"[FAIL] History fetch failed: {exc}")
        return 1

    print("\nDone")
    return 0


if __name__ == "__main__":
    sys.exit(main())
