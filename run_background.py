import errno
import os
import socket
import sys
import traceback
from pathlib import Path

# pythonw.exe（一键重启脚本用它在后台启动）没有控制台：sys.stdout / sys.stderr 为 None，
# 任何报错都会无声消失。这里把它们接到 logs/server_console.log，启动失败时能看到原因。
_CONSOLE_LOG = None
if sys.stdout is None or sys.stderr is None:
    try:
        from runtime_paths import application_data_dir

        log_dir = application_data_dir() / "logs"
    except Exception:
        log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    _CONSOLE_LOG = open(log_dir / "server_console.log", "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = _CONSOLE_LOG
    if sys.stderr is None:
        sys.stderr = _CONSOLE_LOG
    # 常规日志已写入 logs/irontrader.log（带滚动），这里只保留启动信息与异常，避免重复且无限增长
    os.environ["IRONTRADER_CONSOLE_LOG_LEVEL"] = "ERROR"

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def _port_in_use(host: str, port: int) -> bool:
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((probe_host, port)) == 0


def main() -> int:
    import time

    print(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 启动 IronTrader (pid={os.getpid()}) =====", flush=True)
    # 默认仅监听本机（本地运行）。如需局域网/手机访问可设 FLASK_HOST=0.0.0.0。
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5002"))

    if _port_in_use(host, port):
        print(
            f"[IronTrader] 启动失败：端口 {port} 已被其他进程占用。"
            f"请先结束占用该端口的进程（一键重启脚本里输入 R 会自动处理）。",
            flush=True,
        )
        return 2

    try:
        from app import app
    except Exception:
        print("[IronTrader] 启动失败：加载应用时出错", flush=True)
        traceback.print_exc()
        return 1

    # 生产级 WSGI 服务器（waitress，Windows 友好、支持多线程并发）。
    # 未安装则回退到 Flask 自带开发服务器（仅供本地单人使用）。
    try:
        from waitress import serve
    except ImportError:
        print("[IronTrader] 未检测到 waitress，回退 Flask 开发服务器（不建议多端/生产使用）", flush=True)
        app.run(host=host, port=port, debug=False, use_reloader=False)
        return 0

    threads = int(os.getenv("WAITRESS_THREADS", "8"))
    print(f"[IronTrader] waitress 启动于 http://{host}:{port} (threads={threads})", flush=True)
    try:
        serve(app, host=host, port=port, threads=threads)
    except OSError as exc:
        if exc.errno in (errno.EADDRINUSE, 10048):
            print(f"[IronTrader] 启动失败：端口 {port} 已被占用（{exc}）", flush=True)
        else:
            print("[IronTrader] 服务异常退出", flush=True)
            traceback.print_exc()
        return 1
    except Exception:
        print("[IronTrader] 服务异常退出", flush=True)
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
