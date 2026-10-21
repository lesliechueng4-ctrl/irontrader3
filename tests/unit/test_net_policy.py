from net_policy import DOMESTIC_MARKET_DOMAINS, apply_domestic_direct


def test_domestic_domains_are_merged_into_no_proxy_keeping_existing():
    env = {"NO_PROXY": "localhost,127.0.0.1"}
    merged = apply_domestic_direct(env)
    assert merged[:2] == ["localhost", "127.0.0.1"]
    assert "eastmoney.com" in merged and "sse.com.cn" in merged and "szse.cn" in merged
    assert env["NO_PROXY"] == env["no_proxy"] == ",".join(merged)


def test_apply_is_idempotent():
    env = {}
    first = apply_domestic_direct(env)
    second = apply_domestic_direct(env)
    assert first == second == list(DOMESTIC_MARKET_DOMAINS)


def test_can_be_switched_off():
    env = {"IRONTRADER_DIRECT_DOMESTIC": "0", "NO_PROXY": "localhost"}
    assert apply_domestic_direct(env) == []
    assert env["NO_PROXY"] == "localhost"


def test_requests_bypasses_proxy_for_domestic_hosts(monkeypatch):
    import requests.utils

    env = {}
    apply_domestic_direct(env)
    monkeypatch.setenv("NO_PROXY", env["NO_PROXY"])
    monkeypatch.setenv("no_proxy", env["no_proxy"])  # requests 先读小写
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    assert requests.utils.get_environ_proxies("https://82.push2.eastmoney.com/api/qt/clist/get") == {}
    assert requests.utils.get_environ_proxies("https://query.sse.com.cn/x") == {}
    # 境外网站照旧走代理
    assert requests.utils.get_environ_proxies("https://example.org/")
