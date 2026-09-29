from flask import Flask

from auth import UserStore, init_auth
from rate_limit import init_rate_limit

# 模拟经 Cloudflare 隧道进来的公网请求（TCP 对端是本机的 cloudflared，但带 CF 头）
PUBLIC = {"Cf-Connecting-Ip": "203.0.113.9"}


def _app(tmp_path, users=()):
    users_file = tmp_path / "users.json"
    store = UserStore(users_file)
    for username, password, role in users:
        store.create(username, password, role=role)
    app = Flask(__name__)

    @app.route("/")
    def index():
        return "ok"

    @app.route("/api/ping")
    def ping():
        return {"success": True}

    @app.route("/api/analyze/<code>")
    def analyze(code):
        return {"success": True}

    @app.route("/api/backtest/rerun", methods=["POST"])
    def rerun():
        return {"success": True}

    init_auth(app, users_file=users_file)
    init_rate_limit(app)
    return app


OWNER = ("marsi", "owner-pass-123", "owner")
MEMBER = ("阿强", "member-pass-1", "member")


def _login(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password}, headers=PUBLIC)


def test_public_needs_login_local_direct_does_not(tmp_path):
    client = _app(tmp_path, [OWNER]).test_client()
    page = client.get("/", headers=PUBLIC)
    assert page.status_code == 401 and "用户名" in page.get_data(as_text=True)
    assert client.get("/api/ping", headers=PUBLIC).status_code == 401
    assert client.get("/api/ping").status_code == 200  # 本机直连免登录


def test_login_sets_session_and_wrong_password_is_rejected(tmp_path):
    client = _app(tmp_path, [OWNER]).test_client()
    bad = _login(client, "marsi", "wrong-password")
    assert bad.status_code == 401 and bad.get_json()["error"] == "用户名或密码不正确"
    ok = _login(client, "MARSI", "owner-pass-123")  # 用户名不区分大小写
    assert ok.status_code == 200
    cookie = ok.headers["Set-Cookie"]
    assert "it_session=" in cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert "owner-pass-123" not in cookie
    assert client.get("/api/ping", headers=PUBLIC).status_code == 200
    assert client.get("/api/auth/me", headers=PUBLIC).get_json()["data"]["role"] == "owner"
    client.post("/api/auth/logout", headers=PUBLIC)
    assert client.get("/api/ping", headers=PUBLIC).status_code == 401


def test_no_accounts_closes_public_access(tmp_path):
    client = _app(tmp_path).test_client()
    resp = client.get("/api/ping", headers=PUBLIC)
    assert resp.status_code == 401 and "没有创建任何账号" in resp.get_json()["error"]
    assert client.get("/api/ping").status_code == 200


def test_owner_manages_accounts_and_member_is_limited(tmp_path):
    app = _app(tmp_path, [OWNER])
    owner = app.test_client()
    _login(owner, "marsi", "owner-pass-123")

    created = owner.post("/api/admin/users", json={"username": "阿强", "display_name": "阿强"}, headers=PUBLIC)
    assert created.status_code == 200
    initial = created.get_json()["data"]["password"]  # 不填密码时自动生成，只返回这一次
    assert len(initial) >= 8
    assert "password_hash" not in str(owner.get("/api/admin/users", headers=PUBLIC).get_json())

    member = app.test_client()
    assert _login(member, "阿强", initial).status_code == 200
    assert member.get("/api/admin/users", headers=PUBLIC).status_code == 403
    denied = member.post("/api/backtest/rerun", headers=PUBLIC)
    assert denied.status_code == 403 and denied.get_json()["error_code"] == "OWNER_ONLY"

    # 停用后，已登录的会话立即失效
    owner.patch("/api/admin/users/阿强", json={"disabled": True}, headers=PUBLIC)
    assert member.get("/api/ping", headers=PUBLIC).status_code == 401
    assert _login(member, "阿强", initial).status_code == 401


def test_password_reset_logs_out_other_devices(tmp_path):
    app = _app(tmp_path, [OWNER, MEMBER])
    phone, laptop, owner = app.test_client(), app.test_client(), app.test_client()
    _login(phone, "阿强", "member-pass-1")
    _login(laptop, "阿强", "member-pass-1")
    _login(owner, "marsi", "owner-pass-123")

    # 本人改密码：当前设备保持登录，另一台设备掉线
    changed = laptop.post("/api/auth/password", json={"old_password": "member-pass-1", "new_password": "new-pass-456"},
                          headers=PUBLIC)
    assert changed.status_code == 200
    assert laptop.get("/api/ping", headers=PUBLIC).status_code == 200
    assert phone.get("/api/ping", headers=PUBLIC).status_code == 401

    # 管理员重置：返回新密码，本人所有设备掉线
    reset = owner.patch("/api/admin/users/阿强", json={"reset_password": True}, headers=PUBLIC)
    new_password = reset.get_json()["data"]["password"]
    assert laptop.get("/api/ping", headers=PUBLIC).status_code == 401
    assert _login(laptop, "阿强", new_password).status_code == 200


def test_last_owner_cannot_be_removed_and_weak_passwords_rejected(tmp_path):
    app = _app(tmp_path, [OWNER])
    owner = app.test_client()
    _login(owner, "marsi", "owner-pass-123")
    assert owner.delete("/api/admin/users/marsi", headers=PUBLIC).status_code == 400
    assert owner.patch("/api/admin/users/marsi", json={"role": "member"}, headers=PUBLIC).status_code == 400
    weak = owner.post("/api/admin/users", json={"username": "bob", "password": "123"}, headers=PUBLIC)
    assert weak.status_code == 400 and "至少" in weak.get_json()["error"]


def test_member_analyze_rate_limit(tmp_path):
    client = _app(tmp_path, [MEMBER]).test_client()
    _login(client, "阿强", "member-pass-1")
    codes = [client.get(f"/api/analyze/60051{i % 10}", headers=PUBLIC).status_code for i in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429


def test_repeated_wrong_passwords_lock_login(tmp_path):
    client = _app(tmp_path, [OWNER]).test_client()
    for _ in range(10):
        _login(client, "marsi", "guess-guess")
    assert _login(client, "marsi", "owner-pass-123").status_code == 429


def test_session_survives_restart(tmp_path):
    app1 = _app(tmp_path, [OWNER])
    c1 = app1.test_client()
    _login(c1, "marsi", "owner-pass-123")
    cookie = c1.get_cookie("it_session").value

    # "重启"：新建 app，复用同一个数据目录（会话签名密钥持久化在 .session_secret）
    app2 = Flask(__name__)

    @app2.route("/api/ping")
    def ping():
        return {"success": True}

    init_auth(app2, users_file=tmp_path / "users.json")
    c2 = app2.test_client()
    c2.set_cookie("it_session", cookie)
    assert c2.get("/api/ping", headers=PUBLIC).status_code == 200
