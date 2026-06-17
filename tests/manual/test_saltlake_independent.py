# -*- coding: utf-8 -*-
"""Manual AKShare check for saltlake-related stocks.

This script calls live AKShare endpoints, so it lives under tests/manual.
"""
import warnings


warnings.filterwarnings("ignore")


def show_spot_sample(spot):
    print("\n[1] A-share spot sample")
    print(f"[OK] rows={len(spot)}")
    for _, row in spot.head(10).iterrows():
        print(
            f"  {row.get('代码')} {row.get('名称')} "
            f"price={row.get('最新价')} change={row.get('涨跌幅')}"
        )


def show_saltlake_matches(spot):
    print("\n[2] Search saltlake names")
    matches = spot[spot["名称"].astype(str).str.contains("盐湖", na=False)]
    print(f"[OK] matches={len(matches)}")
    for _, row in matches.head(10).iterrows():
        print(
            f"  {row.get('代码')} {row.get('名称')} "
            f"price={row.get('最新价')} change={row.get('涨跌幅')}"
        )


def show_history(code="002924"):
    print(f"\n[3] Historical daily bars for {code}")
    from akshare import stock_zh_a_hist

    history = stock_zh_a_hist(symbol=f"sz{code}", period="daily", adjust="qfq")
    print(f"[OK] rows={len(history)}")
    if len(history) > 0:
        print(history.tail(10).to_string(index=False))


def main():
    print("=" * 80)
    print("Saltlake independent manual smoke test")
    print("=" * 80)

    try:
        from akshare import stock_zh_a_spot_em
    except Exception as exc:
        print(f"[FAIL] AKShare import failed: {exc}")
        return 1

    try:
        spot = stock_zh_a_spot_em()
        show_spot_sample(spot)
        show_saltlake_matches(spot)
        show_history("002924")
    except Exception as exc:
        print(f"[FAIL] AKShare saltlake check failed: {exc}")
        return 1

    print("\nDone")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
