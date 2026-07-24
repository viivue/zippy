"""zippy — local web UI wrapping vidopt, imgopt, and fontslice.

Usage:
    zippy [--port PORT] [--no-open] [--window]

Options:
    --port PORT   Port to bind to (default: 8765)
    --no-open     Don't automatically open a browser tab on start
    --window      Open in a native pywebview window instead of the browser
                  (requires the [window] extra: pip install zippy[window])
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import webbrowser

import uvicorn

DEFAULT_PORT = 8765
HOST = "127.0.0.1"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def _run_server(port: int) -> None:
    from .server import app

    uvicorn.run(app, host=HOST, port=port, log_level="info")


def _open_browser_when_ready(port: int) -> None:
    import time
    import urllib.request

    url = f"http://{HOST}:{port}/"
    for _ in range(100):
        try:
            urllib.request.urlopen(url, timeout=0.5)
            webbrowser.open(url)
            return
        except OSError:
            time.sleep(0.1)


def _run_window(port: int) -> None:
    try:
        import webview
    except ImportError:
        print(
            "pywebview is not installed — install it with: pip install zippy[window]\n"
            "Falling back to browser mode.",
            file=sys.stderr,
        )
        _run_browser_mode(port, no_open=False)
        return

    server_thread = threading.Thread(target=_run_server, args=(port,), daemon=True)
    server_thread.start()

    url = f"http://{HOST}:{port}/"
    webview.create_window("zippy", url)
    webview.start()


def _run_browser_mode(port: int, no_open: bool) -> None:
    if not no_open:
        threading.Thread(
            target=_open_browser_when_ready, args=(port,), daemon=True
        ).start()
    _run_server(port)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="zippy",
        description="Local web UI wrapping vidopt, imgopt, and fontslice.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to bind to (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Don't automatically open a browser tab on start",
    )
    parser.add_argument(
        "--window",
        action="store_true",
        help="Open in a native pywebview window instead of the browser",
    )
    args = parser.parse_args()

    if args.window:
        port = _free_port()
        _run_window(port)
    else:
        _run_browser_mode(args.port, args.no_open)


if __name__ == "__main__":
    main()
