"""
IronTrader 访问控制：账号密码登录 + 角色 + 账号管理 + 审计日志。

谁能访问
- 本机直连（127.0.0.1 / ::1 且没有经过 Cloudflare 隧道等代理）默认免登录，按"管理员"处理；
- 其余请求（公网隧道、局域网）必须先登录；没有任何账号时，公网请求一律拒绝（fail closed）。

账号存在哪
- 数据目录下的 users.json（已加入 .gitignore）。密码只存 PBKDF2 哈希，不存明文。
- 平时不需要手改这个文件：管理员在网页右上角「账号管理」里开账号、重置密码、停用。
- role: owner = 管理员（可回测、重建作战台、管理账号、不受配额限制）；member = 普通成员（受配额限制）。

登录状态
- 登录后发一个签名的会话 cookie（HttpOnly、SameSite=Lax，30 天有效），不含密码。
- 改密码、重置密码、停用账号后，该账号所有已登录的设备立即失效（会话里带密码指纹）。
- 签名密钥存在数据目录的 .session_secret，重启服务不会把大家踢下线。
"""

import hashlib
import json
import os
import re
import secrets
import threading
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional

from flask import Flask, g, has_request_context, jsonify, make_response, request, session
from flask.sessions import SecureCookieSessionInterface
from werkzeug.security import check_password_hash, generate_password_hash

from logger_config import get_logger

logger = get_logger(__name__)

ROLE_OWNER = "owner"
ROLE_MEMBER = "member"
SESSION_DAYS = 30
MIN_PASSWORD_LEN = 8
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-一-龥]{2,20}$")
_HASH_METHOD = "pbkdf2:sha256:600000"

# 不需要登录即可访问的路径（登录接口本身、构建产物）
_PUBLIC_PREFIXES = ("/assets/",)
_PUBLIC_PATHS = {"/favicon.ico", "/api/auth/login", "/api/auth/logout"}

# 代理 / 隧道会带的头：有这些头说明请求来自公网，即使 TCP 对端是 127.0.0.1（cloudflared 在本机）
_PROXY_HEADERS = ("Cf-Connecting-Ip", "Cf-Ray", "X-Forwarded-For", "X-Real-Ip")


class AuthError(ValueError):
    """给用户看的业务错误（用户名重复、密码太短等）。"""


def _fingerprint(password_hash: str) -> str:
    """会话里存的"密码指纹"：密码一变，旧会话全部失效。"""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


class UserStore:
    """users.json 的读写（线程安全、原子写入、外部修改后自动重载）。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._mtime: Optional[float] = None
        self._users: Dict[str, Dict] = {}

    # ---- 读 ----
    def _load(self) -> None:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            self._users, self._mtime = {}, None
            return
        if mtime == self._mtime:
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            users = {}
            for item in data.get("users", []):
                name = str(item.get("username") or "").strip()
                if name and item.get("password_hash"):
                    users[name.lower()] = {
                        "username": name,
                        "display_name": str(item.get("display_name") or name),
                        "role": ROLE_OWNER if item.get("role") == ROLE_OWNER else ROLE_MEMBER,
                        "password_hash": item["password_hash"],
                        "disabled": bool(item.get("disabled")),
                        "note": str(item.get("note") or ""),
                    }
            self._users = users
            logger.info(f"账号表已加载：{len(users)} 个账号")
        except Exception as exc:  # 文件写坏了：保留上一次的配置，别把所有人锁在外面
            logger.error(f"users.json 解析失败，继续使用上一次的账号表: {exc}")
        self._mtime = mtime

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        doc = {
            "_说明": "账号表。请在网页「账号管理」里修改；密码只存哈希。role: owner=管理员, member=成员。",
            "users": sorted(self._users.values(), key=lambda u: (u["role"] != ROLE_OWNER, u["username"].lower())),
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
        self._mtime = self.path.stat().st_mtime

    def get(self, username: str) -> Optional[Dict]:
        with self._lock:
            self._load()
            user = self._users.get(str(username or "").strip().lower())
            return dict(user) if user else None

    def list(self) -> List[Dict]:
        with self._lock:
            self._load()
            return [
                {k: v for k, v in u.items() if k != "password_hash"}
                for u in sorted(self._users.values(), key=lambda u: (u["role"] != ROLE_OWNER, u["username"].lower()))
            ]

    def any_enabled(self) -> bool:
        with self._lock:
            self._load()
            return any(not u["disabled"] for u in self._users.values())

    def verify(self, username: str, password: str) -> Optional[Dict]:
        user = self.get(username)
        if not user or user["disabled"]:
            # 用户不存在时也做一次哈希校验，避免通过响应时间猜出哪些用户名存在
            check_password_hash(_DUMMY_HASH, password or "")
            return None
        return user if check_password_hash(user["password_hash"], password or "") else None

    # ---- 写 ----
    @staticmethod
    def _check_password(password: str) -> None:
        if len(password or "") < MIN_PASSWORD_LEN:
            raise AuthError(f"密码至少 {MIN_PASSWORD_LEN} 位")

    def create(self, username: str, password: str, role: str = ROLE_MEMBER,
               display_name: str = "", note: str = "") -> Dict:
        username = str(username or "").strip()
        if not _USERNAME_RE.match(username):
            raise AuthError("用户名 2–20 位，只能用中英文、数字、下划线、点和横线")
        self._check_password(password)
        with self._lock:
            self._load()
            if username.lower() in self._users:
                raise AuthError("这个用户名已经存在")
            self._users[username.lower()] = {
                "username": username,
                "display_name": (display_name or username).strip()[:20],
                "role": ROLE_OWNER if role == ROLE_OWNER else ROLE_MEMBER,
                "password_hash": generate_password_hash(password, method=_HASH_METHOD),
                "disabled": False,
                "note": note.strip()[:60],
            }
            self._save()
            return {k: v for k, v in self._users[username.lower()].items() if k != "password_hash"}

    def update(self, username: str, **changes) -> Dict:
        with self._lock:
            self._load()
            user = self._users.get(str(username or "").strip().lower())
            if not user:
                raise AuthError("账号不存在")
            if "password" in changes:
                self._check_password(changes["password"])
                user["password_hash"] = generate_password_hash(changes["password"], method=_HASH_METHOD)
            if "role" in changes:
                new_role = ROLE_OWNER if changes["role"] == ROLE_OWNER else ROLE_MEMBER
                if user["role"] == ROLE_OWNER and new_role != ROLE_OWNER and self._owner_count(exclude=user) == 0:
                    raise AuthError("至少要保留一个管理员")
                user["role"] = new_role
            if "disabled" in changes:
                if changes["disabled"] and user["role"] == ROLE_OWNER and self._owner_count(exclude=user) == 0:
                    raise AuthError("不能停用最后一个管理员")
                user["disabled"] = bool(changes["disabled"])
            if "display_name" in changes:
                user["display_name"] = (str(changes["display_name"] or "").strip() or user["username"])[:20]
            if "note" in changes:
                user["note"] = str(changes["note"] or "").strip()[:60]
            self._save()
            return {k: v for k, v in user.items() if k != "password_hash"}

    def delete(self, username: str) -> None:
        with self._lock:
            self._load()
            user = self._users.get(str(username or "").strip().lower())
            if not user:
                raise AuthError("账号不存在")
            if user["role"] == ROLE_OWNER and self._owner_count(exclude=user) == 0:
                raise AuthError("不能删除最后一个管理员")
            del self._users[user["username"].lower()]
            self._save()

    def _owner_count(self, exclude: Optional[Dict] = None) -> int:
        return sum(
            1 for u in self._users.values()
            if u["role"] == ROLE_OWNER and not u["disabled"] and u is not exclude
        )


_DUMMY_HASH = generate_password_hash("irontrader-dummy-password", method=_HASH_METHOD)


def generate_password() -> str:
    """好记一点的随机初始密码：两个英文单词 + 4 位数字，例如 Kite-Moon-4821。"""
    words = ["Kite", "Moon", "Pine", "Wave", "Lion", "Jade", "Star", "Rock", "Leaf", "Snow",
             "Fire", "Bird", "Lake", "Wind", "Gold", "Hill", "Rain", "Tide", "Bear", "Sun"]
    return f"{secrets.choice(words)}-{secrets.choice(words)}-{secrets.randbelow(9000) + 1000}"


def client_ip() -> str:
    forwarded = request.headers.get("Cf-Connecting-Ip") or request.headers.get("X-Forwarded-For", "")
    return (forwarded.split(",")[0].strip() if forwarded else "") or (request.remote_addr or "")


def is_local_direct() -> bool:
    """本机浏览器直连（不经过隧道 / 反向代理）。"""
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return False
    return not any(request.headers.get(h) for h in _PROXY_HEADERS)


def current_user() -> Optional[Dict]:
    if not has_request_context():  # 后台线程、单元测试里直接调用
        return None
    return getattr(g, "it_user", None)


def is_owner() -> bool:
    user = current_user()
    return bool(user and user.get("role") == ROLE_OWNER)


def audit(event: str, **fields) -> None:
    """审计日志：谁在什么时候做了高成本 / 管理操作（写入 irontrader.log，前缀 [audit]）。"""
    user = current_user() or {}
    ip = client_ip() if has_request_context() else "-"
    extra = " ".join(f"{k}={v}" for k, v in fields.items())
    logger.info(f"[audit] {event} user={user.get('name', '?')} ip={ip} {extra}".strip())


class _SessionInterface(SecureCookieSessionInterface):
    """经 https（Cloudflare 隧道）访问时会话 cookie 带 Secure；本机 / 局域网 http 访问时不带，否则浏览器不会回传。"""

    def get_cookie_secure(self, app):
        return bool(has_request_context() and request.is_secure)


def _load_or_create_secret(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
        if len(value) >= 32:
            return value
    except OSError:
        pass
    value = secrets.token_hex(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return value


_LOGIN_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IronTrader · 登录</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; min-height:100vh; display:grid; place-items:center; background:#0f1219; color:#e8ebf2;
         font-family:-apple-system,'PingFang SC','Microsoft YaHei','Segoe UI',sans-serif; }
  form { width:min(360px, calc(100vw - 32px)); background:#161b25; border:1px solid #2a3141; border-radius:12px;
         padding:28px 24px; display:grid; gap:12px; }
  h1 { margin:0 0 4px; font-size:20px; } p { margin:0; color:#7f879a; font-size:13px; line-height:1.6; }
  label { display:grid; gap:6px; font-size:13px; color:#b0b7c6; }
  input { font:inherit; padding:10px 12px; border-radius:8px; border:1px solid #2a3141; background:#0f1219; color:inherit; }
  input:focus { outline:2px solid #7090f0; border-color:transparent; }
  button { font:inherit; font-weight:600; padding:10px; margin-top:4px; border:0; border-radius:8px; background:#7090f0;
           color:#0b0e14; cursor:pointer; }
  button:disabled { opacity:.6; cursor:default; }
  .err { color:#f2877f; min-height:1.2em; }
</style></head>
<body>
<form id="f">
  <h1>IronTrader</h1>
  <p>私人使用的站点，请用管理员给你的账号登录。登录后 30 天内免登录。</p>
  <label>用户名<input id="u" autocomplete="username" autocapitalize="off" autofocus required></label>
  <label>密码<input id="p" type="password" autocomplete="current-password" required></label>
  <button id="b" type="submit">登录</button>
  <p class="err" id="e"></p>
</form>
<script>
document.getElementById('f').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const e = document.getElementById('e'), b = document.getElementById('b');
  e.textContent = ''; b.disabled = true;
  try {
    const r = await fetch('/api/auth/login', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({username: document.getElementById('u').value.trim(),
                            password: document.getElementById('p').value})});
    const j = await r.json();
    if (j.success) location.replace(location.pathname + location.search);
    else e.textContent = j.error || '用户名或密码不正确';
  } catch (err) { e.textContent = '网络错误，请重试'; }
  b.disabled = false;
});
</script>
</body></html>"""


def init_auth(app: Flask, users_file: Path, trust_local: bool = True) -> UserStore:
    """注册登录拦截、登录 / 退出 / 改密码接口和管理员的账号管理接口。"""
    store = UserStore(users_file)
    app.extensions["it_users"] = store
    app.secret_key = _load_or_create_secret(Path(users_file).parent / ".session_secret")
    app.session_interface = _SessionInterface()
    app.config.update(
        SESSION_COOKIE_NAME="it_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=SESSION_DAYS),
    )
    if store.any_enabled():
        logger.info("访问控制已启用（公网请求需要登录）")
    else:
        logger.warning("还没有任何账号：只允许本机直连访问，公网请求将被拒绝")

    from rate_limit import FailedLoginGuard

    login_guard = FailedLoginGuard()

    def _session_user() -> Optional[Dict]:
        username = session.get("u")
        if not username:
            return None
        user = store.get(username)
        # 账号被停用 / 删除 / 改过密码：旧会话失效
        if not user or user["disabled"] or session.get("pv") != _fingerprint(user["password_hash"]):
            session.clear()
            return None
        return {"name": user["display_name"], "username": user["username"], "role": user["role"]}

    def _unauthorized():
        if request.path.startswith("/api/"):
            message = "未登录或登录已过期" if store.any_enabled() else "公网访问已关闭：服务端还没有创建任何账号"
            return jsonify({"success": False, "error": message, "error_code": "UNAUTHORIZED"}), 401
        resp = make_response(_LOGIN_HTML, 401)
        resp.headers["Content-Type"] = "text/html; charset=utf-8"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.before_request
    def check_access():
        path = request.path
        if path.startswith(_PUBLIC_PREFIXES) or path in _PUBLIC_PATHS:
            return None
        if trust_local and is_local_direct():
            g.it_user = {"name": "本机", "username": "", "role": ROLE_OWNER, "local": True}
            return None
        user = _session_user()
        if not user:
            return _unauthorized()
        g.it_user = user
        return None

    # ---------- 登录 / 退出 / 我的信息 / 改自己的密码 ----------
    @app.post("/api/auth/login")
    def auth_login():
        ip = client_ip()
        body = request.get_json(silent=True) or {}
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        blocked = max(login_guard.blocked_for(ip), login_guard.blocked_for(f"user:{username.lower()}"))
        if blocked:
            return jsonify({"success": False, "error": f"尝试次数过多，请 {blocked // 60 + 1} 分钟后再试"}), 429
        user = store.verify(username, password)
        if not user:
            login_guard.record_failure(ip)
            if username:
                login_guard.record_failure(f"user:{username.lower()}")
            logger.warning(f"[access] 登录失败 username={username!r} ip={ip}")
            return jsonify({"success": False, "error": "用户名或密码不正确"}), 401
        session.clear()
        session.permanent = True
        session["u"] = user["username"]
        session["pv"] = _fingerprint(user["password_hash"])
        logger.info(f"[access] 登录 user={user['username']} ip={ip}")
        return jsonify({"success": True, "data": {"name": user["display_name"], "role": user["role"]}})

    @app.post("/api/auth/logout")
    def auth_logout():
        session.clear()
        return jsonify({"success": True, "data": None})

    @app.get("/api/auth/me")
    def auth_me():
        user = current_user() or {}
        return jsonify({"success": True, "data": {
            "name": user.get("name"),
            "username": user.get("username"),
            "role": user.get("role"),
            "local": bool(user.get("local")),
        }})

    @app.post("/api/auth/password")
    def auth_change_password():
        user = current_user() or {}
        if not user.get("username"):
            return jsonify({"success": False, "error": "本机免登录模式没有账号，请在「账号管理」里修改"}), 400
        body = request.get_json(silent=True) or {}
        if not store.verify(user["username"], str(body.get("old_password") or "")):
            return jsonify({"success": False, "error": "原密码不正确"}), 400
        try:
            updated = store.update(user["username"], password=str(body.get("new_password") or ""))
        except AuthError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        fresh = store.get(updated["username"])
        session["pv"] = _fingerprint(fresh["password_hash"])  # 当前设备保持登录，其它设备需重新登录
        audit("password_changed", username=user["username"])
        return jsonify({"success": True, "data": None})

    # ---------- 管理员：账号管理 ----------
    def _owner_guard():
        if not is_owner():
            return jsonify({"success": False, "error": "只有管理员可以管理账号", "error_code": "OWNER_ONLY"}), 403
        return None

    @app.get("/api/admin/users")
    def admin_list_users():
        denied = _owner_guard()
        if denied:
            return denied
        return jsonify({"success": True, "data": store.list()})

    @app.post("/api/admin/users")
    def admin_create_user():
        denied = _owner_guard()
        if denied:
            return denied
        body = request.get_json(silent=True) or {}
        password = str(body.get("password") or "") or generate_password()
        try:
            user = store.create(
                str(body.get("username") or ""), password,
                role=str(body.get("role") or ROLE_MEMBER),
                display_name=str(body.get("display_name") or ""),
                note=str(body.get("note") or ""),
            )
        except AuthError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        audit("user_created", username=user["username"], role=user["role"])
        # 初始密码只在这一次返回，管理员转告对方
        return jsonify({"success": True, "data": {**user, "password": password}})

    @app.patch("/api/admin/users/<username>")
    def admin_update_user(username):
        denied = _owner_guard()
        if denied:
            return denied
        body = request.get_json(silent=True) or {}
        changes = {k: body[k] for k in ("role", "disabled", "display_name", "note") if k in body}
        new_password = None
        if body.get("reset_password"):
            new_password = str(body.get("password") or "") or generate_password()
            changes["password"] = new_password
        try:
            user = store.update(username, **changes)
        except AuthError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        audit("user_updated", username=username, fields=",".join(sorted(changes)))
        return jsonify({"success": True, "data": {**user, **({"password": new_password} if new_password else {})}})

    @app.delete("/api/admin/users/<username>")
    def admin_delete_user(username):
        denied = _owner_guard()
        if denied:
            return denied
        try:
            store.delete(username)
        except AuthError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        audit("user_deleted", username=username)
        return jsonify({"success": True, "data": None})

    return store


__all__ = [
    "AuthError",
    "ROLE_MEMBER",
    "ROLE_OWNER",
    "UserStore",
    "audit",
    "client_ip",
    "current_user",
    "generate_password",
    "init_auth",
    "is_local_direct",
    "is_owner",
]
