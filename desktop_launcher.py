"""Desktop entry point used by the Windows distribution."""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def _server_is_ready(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _open_browser_when_ready(url: str, host: str, port: int) -> None:
    if os.getenv("IRONTRADER_OPEN_BROWSER", "1").lower() in {"0", "false", "no"}:
        return
    for _ in range(30):
        if _server_is_ready(host, port):
            webbrowser.open(url)
            return
        time.sleep(0.25)


def main() -> None:
    os.environ.setdefault("FLASK_HOST", "127.0.0.1")
    os.environ.setdefault("FLASK_PORT", "5002")
    os.environ.setdefault("FLASK_DEBUG", "False")

    host = os.environ["FLASK_HOST"]
    port = int(os.environ["FLASK_PORT"])
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{browser_host}:{port}"

    if _server_is_ready(browser_host, port):
        print(f"[IronTrader] Port {port} is already in use. Opening the existing service: {url}")
        webbrowser.open(url)
        return

    from app import app

    print(f"[IronTrader] Starting service at {url}")
    print("[IronTrader] Keep this window open while using the application. Press Ctrl+C to stop it.")
    threading.Thread(
        target=_open_browser_when_ready,
        args=(url, browser_host, port),
        daemon=True,
    ).start()

    try:
        from waitress import serve

        serve(app, host=host, port=port, threads=int(os.getenv("WAITRESS_THREADS", "8")))
    except KeyboardInterrupt:
        print("\n[IronTrader] Service stopped.")


if __name__ == "__main__":
    main()
