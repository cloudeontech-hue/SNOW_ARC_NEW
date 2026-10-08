"""Native desktop shell for SNOW ARC.

Runs the exact same `run_dashboard` backend and HTML/JS frontend used by the
live web deployment, in a local pywebview window instead of a browser tab.
Does not replace `run_dashboard.py` — just wraps it. No Electron, no Node.
"""
import os
import socket
import sys
import threading
import time
from pathlib import Path

if sys.platform.startswith("linux"):
    # This system's WebKitGTK crashes intermittently under the default Wayland/
    # bwrap-sandbox path (a snap-vs-host glibc symbol clash triggered during
    # sandboxed process spawn). Forcing X11 and disabling the sandbox avoids it.
    # Must be set before `import webview` triggers GTK/GDK initialization.
    os.environ.setdefault("GDK_BACKEND", "x11")
    os.environ.setdefault("WEBKIT_DISABLE_SANDBOX", "1")

import webview


def _resource_base_dir() -> Path:
    """Directory containing the site files (index.html, assets/, backend/, ...).

    - Frozen `--onefile` build: PyInstaller extracts bundled data to `sys._MEIPASS`.
    - Frozen `--onedir` build: bundled data sits next to the executable.
    - Unfrozen (`python desktop_app.py`): the repo root, same as normal dev/web.
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_server(port: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _load_with_retries(window, url: str, attempts: int = 5, settle_delay: float = 1.0) -> None:
    """Navigate `window` to `url`, retrying if the load doesn't complete.

    On this system, WebKitGTK's network process can crash once or twice right
    after the GTK main loop starts (a snap-vs-host glibc symbol clash during
    process spawn — see the GDK_BACKEND/WEBKIT_DISABLE_SANDBOX note above).
    WebKit auto-respawns the crashed process, but doesn't retry whatever page
    load was in flight, so a URL handed to `create_window` up front can be
    left stuck on a blank page. Loading only after the main loop is up, and
    re-issuing load_url if `loaded` doesn't fire, rides out that window.
    """
    for attempt in range(1, attempts + 1):
        window.events.loaded.clear()
        window.load_url(url)
        if window.events.loaded.wait(settle_delay + attempt):
            return
    # Final attempt: leave it loading: if the page truly can't come up, the
    # window will show whatever error WebKit renders instead of just blank.


def main():
    # run_dashboard.serve_static() resolves HTML/asset paths relative to the
    # working directory, and dotenv.load_dotenv() reads `.env` the same way —
    # so cwd must point at the bundled site files before either runs.
    os.chdir(_resource_base_dir())

    from run_dashboard import run  # imported after chdir, see above

    port = _free_port()
    server_thread = threading.Thread(target=run, kwargs={"port": port}, daemon=True)
    server_thread.start()

    if not _wait_for_server(port):
        raise RuntimeError("Dashboard server did not start in time")

    window = webview.create_window(
        "SNOW ARC",
        width=1280,
        height=800,
        min_size=(1024, 700),
    )
    # Blocks until the window is closed, then returns; the server thread is a
    # daemon, so it's killed automatically when the process exits below —
    # no orphaned process left behind. The real page is loaded from `func`,
    # which pywebview runs once the GTK main loop is actually up — see
    # `_load_with_retries` for why this two-step load matters on Linux.
    webview.start(_load_with_retries, (window, f"http://127.0.0.1:{port}/"))


if __name__ == "__main__":
    main()
