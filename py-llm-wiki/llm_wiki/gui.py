"""Desktop GUI launcher.

Starts the FastAPI backend (uvicorn) on a background thread bound to localhost,
then opens a native window pointing at it via pywebview. Closing the window
stops the process. Falls back to opening the system browser if pywebview is
unavailable.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from .store import WikiProject


def _wait_for_server(host: str, port: int, timeout: float = 10.0) -> bool:
    import socket

    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.1)
    return False


def launch(project: WikiProject, *, port: int = 8765, host: str = "127.0.0.1") -> int:
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise ImportError("uvicorn") from exc

    from .api import create_app

    app = create_app(project)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    url = f"http://{host}:{port}/"
    if not _wait_for_server(host, port):
        print(f"error: server did not start on {url}")
        return 1

    print(f"LLM Wiki GUI serving at {url}")

    try:
        import webview  # pywebview

        window = webview.create_window("LLM Wiki", url, width=1280, height=800)
        webview.start()
        # When the window closes, stop the server and exit.
        server.should_exit = True
        return 0
    except ImportError:
        # No pywebview — open in the default browser and block.
        import webbrowser

        print("pywebview not installed; opening in your browser. Press Ctrl+C to stop.")
        webbrowser.open(url)
        try:
            while thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            server.should_exit = True
        return 0
