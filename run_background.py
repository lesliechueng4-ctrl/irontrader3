import os
import sys


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


from app import app


if __name__ == "__main__":
    # 默认仅监听本机（本地运行）。如需局域网访问可设 FLASK_HOST=0.0.0.0。
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5002"))
    app.run(host=host, port=port, debug=False, use_reloader=False)
