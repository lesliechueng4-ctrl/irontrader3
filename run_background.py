import os
import sys


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


from app import app


if __name__ == "__main__":
    # 默认仅监听本机（本地运行）。如需局域网/手机访问可设 FLASK_HOST=0.0.0.0。
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5002"))
    # 生产级 WSGI 服务器（waitress，Windows 友好、支持多线程并发）。
    # 未安装则回退到 Flask 自带开发服务器（仅供本地单人使用）。
    try:
        from waitress import serve
        threads = int(os.getenv("WAITRESS_THREADS", "8"))
        print(f"[IronTrader] waitress 启动于 http://{host}:{port} (threads={threads})")
        serve(app, host=host, port=port, threads=threads)
    except ImportError:
        print("[IronTrader] 未检测到 waitress，回退 Flask 开发服务器（不建议多端/生产使用）")
        app.run(host=host, port=port, debug=False, use_reloader=False)
