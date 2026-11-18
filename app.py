import json
import secrets
import threading
from dataclasses import dataclass, field
from datetime import date, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from Test import SPH, SPHError, _overlaps, merge_consecutive_lessons


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
SESSIONS = {}
SESSIONS_LOCK = threading.Lock()


@dataclass
class PortalSession:
    client: SPH
    lock: threading.RLock = field(default_factory=threading.RLock)
    allowed_message_urls: set = field(default_factory=set)


def current_session(handler):
    cookies = SimpleCookie(handler.headers.get("Cookie", ""))
    cookie = cookies.get("sph_session")
    if cookie is None:
        return None, None
    session_id = cookie.value
    with SESSIONS_LOCK:
        return session_id, SESSIONS.get(session_id)


class PortalHandler(BaseHTTPRequestHandler):
    server_version = "SchulportalWeb/1.0"

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_get_api(parsed.path, parse_qs(parsed.query))
            return
        self.serve_static(parsed.path)

    def do_POST(self):
        parsed = urlsplit(self.path)
        if not parsed.path.startswith("/api/"):
            self.send_error(404)
            return
        try:
            data = self.read_json()
            self.handle_post_api(parsed.path, data)
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except SPHError as error:
            self.send_json(401, {"error": str(error)})
        except httpx.HTTPError as error:
            self.send_json(502, {"error": f"Schulportal request failed: {error}"})

    def read_json(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size > 1_000_000:
                raise ValueError("Request body is too large.")
            data = json.loads(self.rfile.read(size) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("Request body must be valid JSON.") from error
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object.")
        return data

    def handle_get_api(self, path, query):
        if path == "/api/session":
            _, session = current_session(self)
            self.send_json(200, {
                "authenticated": session is not None,
                "school": session.client.school if session else None,
                "user": session.client.user if session else None,
            })
            return

        _, session = current_session(self)
        if session is None:
            self.send_json(401, {"error": "Please sign in to Schulportal first."})
            return

        try:
            with session.lock:
                if path == "/api/week":
                    requested = self.require_date(query)
                    monday = requested - timedelta(days=requested.weekday())
                    self.send_json(200, self.week_data(session.client, monday))
                elif path == "/api/substitutions":
                    self.send_json(200, {"substitutions": session.client.substitution_plan()})
                elif path == "/api/homework":
                    self.send_json(200, {"text": session.client.homework()})
                elif path == "/api/applications":
                    links = session.client.discover_applications()
                    session.allowed_message_urls.update(item["url"] for item in links)
                    self.send_json(200, {"applications": links})
                elif path == "/api/dashboard":
                    page = session.client.dashboard()
                    soup = BeautifulSoup(page.text, "html.parser")
                    links = [{
                        "name": anchor.get_text(" ", strip=True),
                        "url": urljoin(str(page.url), anchor["href"]),
                    } for anchor in soup.find_all("a", href=True)]
                    forms = [{
                        "action": urljoin(str(page.url), form.get("action") or str(page.url)),
                        "method": (form.get("method") or "GET").upper(),
                    } for form in soup.find_all("form")]
                    self.send_json(200, {
                        "url": str(page.url),
                        "links": links,
                        "forms": forms,
                    })
                elif path == "/api/messages/open":
                    target = query.get("url", [""])[0]
                    if target not in session.allowed_message_urls:
                        raise ValueError("Open a discovered message link instead.")
                    result = session.client.inspect_message_page(target)
                    session.allowed_message_urls.update(link["url"] for link in result["links"])
                    self.send_json(200, result)
                else:
                    self.send_json(404, {"error": "Unknown API endpoint."})
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except SPHError as error:
            self.send_json(401, {"error": str(error)})
        except httpx.HTTPError as error:
            self.send_json(502, {"error": f"Schulportal request failed: {error}"})

    def handle_post_api(self, path, data):
        if path == "/api/login":
            school = str(data.get("school", "")).strip()
            user = str(data.get("user", "")).strip()
            password = str(data.get("password", ""))
            if not school or not user or not password:
                raise ValueError("Enter your school ID, username, and password.")

            client = SPH(school, user, password)
            try:
                client.login()
            except (SPHError, httpx.HTTPError):
                client.close()
                raise

            session_id = secrets.token_urlsafe(32)
            with SESSIONS_LOCK:
                SESSIONS[session_id] = PortalSession(client)
            self.send_json(
                200,
                {"authenticated": True, "school": school, "user": user},
                cookie=f"sph_session={session_id}; HttpOnly; SameSite=Strict; Path=/",
            )
            return

        session_id, session = current_session(self)
        if path == "/api/logout":
            if session_id:
                with SESSIONS_LOCK:
                    removed = SESSIONS.pop(session_id, None)
                if removed:
                    with removed.lock:
                        removed.client.close()
            self.send_json(
                200,
                {"authenticated": False},
                cookie="sph_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0",
            )
            return

        if path == "/api/messages/open":
            if session is None:
                self.send_json(401, {"error": "Please sign in to Schulportal first."})
                return
            target = str(data.get("url", ""))
            with session.lock:
                if target not in session.allowed_message_urls:
                    self.send_json(400, {"error": "Open a discovered message link instead."})
                    return
                result = session.client.inspect_message_page(target)
                session.allowed_message_urls.update(link["url"] for link in result["links"])
            self.send_json(200, result)
            return

        self.send_json(404, {"error": "Unknown API endpoint."})

    @staticmethod
    def require_date(query):
        raw = query.get("date", [""])[0]
        try:
            return date.fromisoformat(raw)
        except ValueError as error:
            raise ValueError("Choose a valid date in YYYY-MM-DD format.") from error

    @staticmethod
    def week_data(client, monday):
        timetable = client.timetable()
        plan = timetable["own"] if timetable["own"] is not None else timetable["all"]
        substitutions = []
        substitution_error = None
        try:
            substitutions = client.substitution_plan()
        except (SPHError, httpx.HTTPError, ValueError) as error:
            substitution_error = str(error)

        days = []
        for offset in range(5):
            day = monday + timedelta(days=offset)
            lessons = sorted(plan[day.weekday()], key=lambda lesson: lesson["hour"]) if day.weekday() < len(plan) else []
            applicable = [item for item in substitutions if item.get("Tag_en") == day.isoformat()]
            for lesson in lessons:
                lesson["changes"] = [item for item in applicable if _overlaps(lesson, item)]
            lessons = merge_consecutive_lessons(lessons)
            for index, lesson in enumerate(lessons):
                lesson["id"] = f"{day.isoformat()}-{index}"
            days.append({
                "date": day.isoformat(),
                "weekday": day.strftime("%A"),
                "lessons": lessons,
            })

        return {
            "week": timetable.get("week"),
            "days": days,
            "personal_timetable": timetable["own"] is not None,
            "substitution_error": substitution_error,
        }

    def serve_static(self, requested_path):
        relative = "index.html" if requested_path == "/" else requested_path.lstrip("/")
        target = (WEB_ROOT / relative).resolve()
        if not target.is_relative_to(WEB_ROOT.resolve()) or not target.is_file():
            self.send_error(404)
            return
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
        }.get(target.suffix, "application/octet-stream")
        content = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, status, data, cookie=None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string, *args):
        print(f"[web] {self.address_string()} - {format_string % args}")


def main():
    host = "127.0.0.1"
    port = 8000
    server = ThreadingHTTPServer((host, port), PortalHandler)
    print(f"Schulportal web app running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Schulportal web app.")
    finally:
        server.server_close()
        with SESSIONS_LOCK:
            sessions = list(SESSIONS.values())
            SESSIONS.clear()
        for session in sessions:
            session.client.close()


if __name__ == "__main__":
    main()
