from pathlib import Path
import threading
from http.server import ThreadingHTTPServer

import app


_server = None
_server_thread = None
_active_clients = 0
_lifecycle_lock = threading.Lock()


def start(web_root):
    global _server, _server_thread, _active_clients
    root = Path(web_root).resolve()
    if not root.is_dir():
        raise RuntimeError(f"Web assets directory does not exist: {root}")

    with _lifecycle_lock:
        if _server is None:
            app.WEB_ROOT = root
            server = ThreadingHTTPServer(("127.0.0.1", 0), app.PortalHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            try:
                thread.start()
            except Exception:
                server.server_close()
                raise
            _server = server
            _server_thread = thread
        _active_clients += 1
        return _server.server_address[1]


def stop():
    global _server, _server_thread, _active_clients
    with _lifecycle_lock:
        if _active_clients == 0:
            return
        _active_clients -= 1
        if _active_clients > 0 or _server is None:
            return

        server = _server
        thread = _server_thread
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join()
        _server = None
        _server_thread = None

        with app.SESSIONS_LOCK:
            sessions = list(app.SESSIONS.values())
            app.SESSIONS.clear()
        for session in sessions:
            with session.lock:
                session.client.close()
