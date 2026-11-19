import json
import sys
import threading
from http.server import ThreadingHTTPServer

import bs4
import httpx
import Test
import app


_server = None
_server_thread = None


def _smoke_test():
    html = """
    <table id="aktuelleWoche"><tr><td>Week 42</td></tr></table>
    <table id="own"><tbody>
      <tr><td></td><td>Monday <span class="VonBis">08:00 - 08:45</span></td></tr>
      <tr>
        <td><span class="print-show"><b>1</b></span></td>
        <td><div class="stunde"><b>Mathematics</b> Room 12 <small>ABC</small></div></td>
      </tr>
    </tbody></table>
    """
    timetable = Test.parse_timetable(html)
    lesson = timetable["own"][0][0]
    if lesson["name"] != "Mathematics" or lesson["start"] != "08:00":
        raise RuntimeError("Existing timetable parser smoke test failed.")
    if app.PortalHandler is None:
        raise RuntimeError("Existing API backend did not import.")
    return lesson


class Handler(app.PortalHandler):
    def serve_static(self, requested_path):
        body_data = json.dumps({
            "python": sys.version.split()[0],
            "httpx": httpx.__version__,
            "beautifulsoup4": bs4.__version__,
            "parsed_lesson": _smoke_test(),
        }, ensure_ascii=False)
        body = f"""<!doctype html>
            <html><meta name="viewport" content="width=device-width">
            <title>Android feasibility</title>
            <body><h1>Embedded Python is running</h1>
            <pre id="result">Checking existing API…</pre>
            <script>
              const details = {body_data};
              fetch('/api/session').then(r => r.json()).then(session => {{
                details.api_session = session;
                document.querySelector('#result').textContent =
                  JSON.stringify(details, null, 2);
              }}).catch(error => {{
                document.querySelector('#result').textContent = String(error);
              }});
            </script></body></html>""".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string, *args):
        return


def start():
    global _server, _server_thread
    if _server is None:
        _smoke_test()
        _server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        _server_thread = threading.Thread(target=_server.serve_forever, daemon=True)
        _server_thread.start()
    return _server.server_address[1]
