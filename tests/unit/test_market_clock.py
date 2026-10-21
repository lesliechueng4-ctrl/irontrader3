from datetime import date, datetime

from market_clock import TZ, is_live, last_close, snapshot_is_final


def _trading(day: date) -> bool:
    # 2026-10-21 周三开市；2026-10-01 国庆休市
    return day.weekday() < 5 and day != date(2026, 10, 1)


def at(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def test_live_windows_include_auction_and_settle_buffer():
    assert is_live(at(2026, 10, 21, 9, 20), _trading)        # 集合竞价
    assert is_live(at(2026, 10, 21, 11, 31), _trading)       # 午间收盘后 2 分钟内仍在变
    assert not is_live(at(2026, 10, 21, 12, 0), _trading)    # 午休
    assert is_live(at(2026, 10, 21, 14, 59), _trading)
    assert not is_live(at(2026, 10, 21, 15, 5), _trading)    # 收盘后
    assert not is_live(at(2026, 10, 24, 10, 0), _trading)    # 周六
    assert not is_live(at(2026, 10, 1, 10, 0), _trading)     # 节假日


def test_last_close_points_to_lunch_close_close_or_previous_trading_day():
    assert last_close(at(2026, 10, 21, 12, 10), _trading) == at(2026, 10, 21, 11, 32)
    assert last_close(at(2026, 10, 21, 18, 0), _trading) == at(2026, 10, 21, 15, 2)
    assert last_close(at(2026, 10, 21, 8, 0), _trading) == at(2026, 10, 20, 15, 2)
    assert last_close(at(2026, 10, 25, 10, 0), _trading) == at(2026, 10, 23, 15, 2)  # 周日看周五
    assert last_close(at(2026, 10, 21, 10, 0), _trading) is None                      # 盘中


def test_snapshot_is_final_only_when_taken_after_the_last_close():
    noon = at(2026, 10, 21, 12, 10)
    assert snapshot_is_final(at(2026, 10, 21, 11, 33), noon, _trading)
    assert not snapshot_is_final(at(2026, 10, 21, 11, 20), noon, _trading)  # 午休前取的，要重拉一次
    assert not snapshot_is_final(at(2026, 10, 21, 10, 0), at(2026, 10, 21, 10, 1), _trading)  # 盘中永远不算
    # 周五收盘后取的快照，周末一直有效
    assert snapshot_is_final(at(2026, 10, 23, 15, 10), at(2026, 10, 25, 20, 0), _trading)
