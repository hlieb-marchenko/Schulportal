
"""
Schulportal Hessen (Lanis) — Interactive CLI Client

Dependencies:
    pip install httpx beautifulsoup4

Environment:
    SPH_SCHOOL=1234
    SPH_USER=firstname.lastname
    SPH_PASS=your-password

Run:
    python sph_client.py
    python sph_client.py --debug
"""

import os
import re
import sys
from datetime import date, timedelta, datetime
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup


LOGIN = "https://login.schulportal.hessen.de/"
CONNECT = "https://connect.schulportal.hessen.de/"
BASE = "https://start.schulportal.hessen.de/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) "
        "Gecko/20100101 Firefox/128.0"
    )
}

MESSAGE_KEYWORDS = (
    "nachricht",
    "postfach",
    "message",
    "kommunikation",
    "mitteilung",
    "unterhaltung",
)


class SPHError(Exception):
    pass


# ============================================================
# TIMETABLE PARSING
# ============================================================

def _vonbis(el):
    m = re.fullmatch(
        r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*",
        el.get_text()
    )

    if not m:
        return None

    a, b, c, d = map(int, m.groups())

    return f"{a:02d}:{b:02d}", f"{c:02d}:{d:02d}"


def parse_plan(tbody):
    if tbody is None:
        return []

    rows = tbody.find_all("tr", recursive=False)

    if not rows:
        return []

    day_count = (
        len(rows[0].find_all(["td", "th"], recursive=False)) - 1
    )

    if day_count <= 0:
        return []

    days = [[] for _ in range(day_count)]

    slots = [
        s for s in (
            _vonbis(e) for e in tbody.select(".VonBis")
        ) if s
    ]

    done = [[False] * day_count for _ in range(len(rows) + 32)]

    labels = []

    for r in rows:
        c0 = r.find(["td", "th"], recursive=False)
        b = c0.select_one(".print-show b") if c0 else None

        t = b.get_text(strip=True) if b else ""

        labels.append(int(t) if t.isdigit() else None)

    first_cells = rows[0].find_all(
        ["td", "th"], recursive=False
    )

    offset_first = bool(
        first_cells and first_cells[0].get_text().strip()
    )

    for y, row in enumerate(rows):
        if y == 0:
            continue

        cells = row.find_all(
            ["td", "th"], recursive=False
        )

        for col, cell in enumerate(cells):
            if col == 0:
                continue

            try:
                span = int(cell.get("rowspan", "1"))
            except ValueError:
                span = 1

            day = col - 1

            while day < day_count and done[y][day]:
                day += 1

            if day >= day_count:
                continue

            for i in range(span):
                if y + i < len(done):
                    done[y + i][day] = True

            for les in cell.select(".stunde"):
                bold = les.find("b")

                name = (
                    bold.get_text(strip=True)
                    if bold else None
                )

                room = " ".join(
                    t.strip()
                    for t in les.find_all(
                        string=True,
                        recursive=False
                    )
                    if t.strip()
                )

                small = les.find("small")

                teacher = (
                    small.get_text(strip=True)
                    if small else ""
                )

                badge = les.select_one(".badge")

                start_i = y if offset_first else y - 1
                end_i = start_i + span - 1

                if (
                    0 <= start_i < len(slots)
                    and 0 <= end_i < len(slots)
                ):
                    start, end = (
                        slots[start_i][0],
                        slots[end_i][1]
                    )
                else:
                    start = end = None

                nums = [
                    n for n in labels[y:y + span]
                    if n is not None
                ]

                days[day].append({
                    "hour": y,
                    "hours": span,
                    "from_hour": min(nums) if nums else None,
                    "to_hour": max(nums) if nums else None,
                    "name": name,
                    "room": room,
                    "teacher": teacher or None,
                    "badge": (
                        badge.get_text(strip=True)
                        if badge else None
                    ),
                    "start": start,
                    "end": end,
                })

    return days


def parse_timetable(html):
    soup = BeautifulSoup(html, "html.parser")

    wk = soup.select_one("#aktuelleWoche")
    own = soup.select_one("#own tbody")
    allp = soup.select_one("#all tbody")

    return {
        "week": wk.get_text(strip=True) if wk else None,
        "own": parse_plan(own) if own else None,
        "all": parse_plan(allp) if allp else None,
    }

def merge_consecutive_lessons(lessons):
    """
    Merge consecutive lessons if all relevant information
    is identical and the end time of one equals the start
    time of the next.
    """

    if not lessons:
        return []

    lessons = sorted(
        lessons,
        key=lambda l: l["hour"]
    )

    merged = []

    for lesson in lessons:
        current = lesson.copy()

        if not merged:
            merged.append(current)
            continue

        previous = merged[-1]

        same_details = all(
            previous.get(key) == current.get(key)
            for key in (
                "name",
                "room",
                "teacher",
                "badge",
                "changes",
            )
        )

        consecutive = (
            previous.get("end")
            and current.get("start")
            and previous["end"] == current["start"]
        )

        if same_details and consecutive:
            previous["end"] = current["end"]
            previous["hours"] += current.get("hours", 1)

            if current.get("to_hour") is not None:
                previous["to_hour"] = current["to_hour"]

        else:
            merged.append(current)

    return merged


def _hour_range(text):
    nums = [
        int(n) for n in re.findall(r"\d+", text or "")
    ]

    return (min(nums), max(nums)) if nums else None



def _normalize_teacher(value):
    """Normalize teacher abbreviations for reliable comparison."""
    if not value:
        return None

    return re.sub(
        r"[^a-z0-9]",
        "",
        value.lower().strip()
    )


def _overlaps(lesson, sub):
    """
    A substitution is relevant only if:
    1. The student has a lesson with that teacher.
    2. The lesson overlaps the substitution hours.
    """

    rng = _hour_range(sub.get("Stunde"))

    if not rng:
        return False

    lesson_teacher = _normalize_teacher(
        lesson.get("teacher")
    )

    substitution_teacher = _normalize_teacher(
        sub.get("Lehrerkuerzel")
    )

    if not lesson_teacher or not substitution_teacher:
        return False

    if lesson_teacher != substitution_teacher:
        return False

    lesson_start = lesson.get("from_hour")
    lesson_end = lesson.get("to_hour")

    if lesson_start is None or lesson_end is None:
        return False

    return (
        rng[0] <= lesson_end
        and lesson_start <= rng[1]
    )

    rng = _hour_range(sub.get("Stunde"))

    if not rng or lesson.get("from_hour") is None:
        return False

    same_teacher = (
        lesson.get("teacher")
        and lesson["teacher"] == sub.get("Lehrerkuerzel")
    )

    hours_overlap = (
        rng[0] <= lesson["to_hour"]
        and lesson["from_hour"] <= rng[1]
    )

    return bool(same_teacher and hours_overlap)


def next_school_day(today=None):
    d = (today or date.today()) + timedelta(days=1)

    while d.weekday() >= 5:
        d += timedelta(days=1)

    return d


# ============================================================
# SCHULPORTAL CLIENT
# ============================================================

class SPH:

    def __init__(
        self,
        school,
        user,
        password,
        debug=False
    ):
        self.school = school
        self.user = user
        self.password = password
        self.debug = debug

        self.http = httpx.Client(
            headers=HEADERS,
            follow_redirects=True,
            timeout=30
        )

        self.message_links = []

    def _log(self, *args):
        if self.debug:
            print("[DEBUG]", *args, file=sys.stderr)

    def close(self):
        self.http.close()

    # --------------------------------------------------------
    # HTTP
    # --------------------------------------------------------

    def request(self, method, url, **kwargs):
        if not url.startswith("http"):
            url = urljoin(BASE, url)

        r = self.http.request(method, url, **kwargs)

        self._log(
            method,
            r.status_code,
            r.url
        )

        self._check(r)

        return r

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, data=None, **kwargs):
        return self.request(
            "POST",
            path,
            data=data or {},
            **kwargs
        )

    @staticmethod
    def _check(r):
        if "login.schulportal.hessen.de" in str(r.url):
            raise SPHError(
                "Session expired or redirected to login."
            )

        r.raise_for_status()

    # --------------------------------------------------------
    # LOGIN
    # --------------------------------------------------------

    def login(self):

        self._log("Starting login...")

        r = self.post(
            LOGIN,
            params={"i": self.school},
            data={
                "user2": self.user,
                "user": f"{self.school}.{self.user}",
                "password": self.password,
            },
        )

        if not any(
            c.name == "SPH-Session"
            for c in self.http.cookies.jar
        ):
            raise SPHError(
                "No SPH-Session cookie. "
                "Check credentials or login flow."
            )

        self._log("SPH session acquired.")

        r = self.get(CONNECT)

        if not any(
            c.name == "sid"
            for c in self.http.cookies.jar
        ):
            raise SPHError(
                f"No sid cookie after connecting. "
                f"Final URL: {r.url}"
            )

        self._log("SID acquired.")

    # --------------------------------------------------------
    # TIMETABLE
    # --------------------------------------------------------

    def timetable(self):
        page = self.get("stundenplan.php")

        return parse_timetable(page.text)

    def substitution_plan(self):
        page = self.get("vertretungsplan.php")

        soup = BeautifulSoup(
            page.text,
            "html.parser"
        )

        h3 = soup.select_one(
            "div.panel-info div.panel-body h3"
        )

        m = re.search(
            r"\d\d\.\d\d\.\d{4}",
            h3.get_text() if h3 else ""
        )

        if not m:
            raise SPHError(
                "Could not find substitution date."
            )

        response = self.post(
            "vertretungsplan.php",
            {
                "ganzerPlan": "true",
                "tag": m.group(0)
            }
        )

        return response.json()

    def schedule_for(self, day):

        tt = self.timetable()

        plan = (
            tt["own"]
            if tt["own"] is not None
            else tt["all"]
        )

        if tt["own"] is None:
            print(
                "[WARNING] Personal timetable unavailable. "
                "Using full school timetable."
            )

        wd = day.weekday()

        lessons = (
            sorted(
                plan[wd],
                key=lambda l: l["hour"]
            )
            if wd < len(plan)
            else []
        )

        try:
            subs = [
                s for s in self.substitution_plan()
                if s.get("Tag_en") == day.isoformat()
            ]
        except Exception as e:
            self._log("Substitutions unavailable:", e)
            subs = []

        for lesson in lessons:
            lesson["changes"] = [
                s for s in subs if _overlaps(lesson, s)
            ]

        lessons = merge_consecutive_lessons(lessons)

        return lessons, tt

    # --------------------------------------------------------
    # HOMEWORK
    # --------------------------------------------------------

    def homework_page(self):
        page = self.get("meinunterricht.php")

        return BeautifulSoup(
            page.text,
            "html.parser"
        )

    def homework(self):
        return self.homework_page().get_text(
            "\n",
            strip=True
        )

    # --------------------------------------------------------
    # APPLICATION DISCOVERY
    # --------------------------------------------------------

    def dashboard(self):
        """
        Load the main portal page.
        """

        return self.get("index.php")

    def discover_applications(self):
        """
        Search the dashboard for application links.
        """

        print("\nSearching available applications...")

        page = self.dashboard()

        soup = BeautifulSoup(
            page.text,
            "html.parser"
        )

        found = {}

        for a in soup.find_all("a", href=True):

            label = a.get_text(
                " ",
                strip=True
            )

            href = a["href"]

            if not href or href.startswith(
                ("#", "javascript:", "mailto:")
            ):
                continue

            absolute = urljoin(str(page.url), href)

            parsed = urlparse(absolute)

            if parsed.scheme not in ("http", "https"):
                continue

            text = (
                label + " " + href
            ).lower()

            if any(
                keyword in text
                for keyword in MESSAGE_KEYWORDS
            ):
                found[absolute] = label or href

        self.message_links = [
            {
                "name": name,
                "url": url
            }
            for url, name in found.items()
        ]

        if self.message_links:
            print("\nMessage-related applications found:")

            for i, item in enumerate(
                self.message_links,
                1
            ):
                print(
                    f"  {i}. {item['name']}"
                )

        else:
            print(
                "\nNo message-related links found "
                "on the main dashboard."
            )

            print(
                "This does not necessarily mean "
                "that Nachrichten is unavailable."
            )

        return self.message_links

    # --------------------------------------------------------
    # MESSAGE APPLICATION
    # --------------------------------------------------------

    def inspect_message_page(self, url):
        """
        Load a discovered message page and extract readable
        text and links.

        This is generic HTML inspection, not an assumption
        about a particular Nachrichten API.
        """

        page = self.get(url)

        soup = BeautifulSoup(
            page.text,
            "html.parser"
        )

        # Remove scripts and styling.
        for element in soup.select(
            "script, style, noscript"
        ):
            element.decompose()

        print("\n" + "=" * 70)
        print("PAGE:", page.url)
        print("=" * 70)

        title = soup.title

        if title:
            print(
                "\nTITLE:",
                title.get_text(strip=True)
            )

        main = (
            soup.select_one("main")
            or soup.select_one("#content")
            or soup.select_one(".container")
            or soup.body
            or soup
        )

        text = main.get_text(
            "\n",
            strip=True
        )

        print("\nPAGE CONTENT:\n")
        print(text[:15000])

        if len(text) > 15000:
            print("\n[Content truncated]")

        links = []

        for a in main.find_all(
            "a",
            href=True
        ):
            label = a.get_text(
                " ",
                strip=True
            )

            href = a["href"]

            if (
                not label
                or href.startswith(
                    ("#", "javascript:", "mailto:")
                )
            ):
                continue

            absolute = urljoin(
                str(page.url),
                href
            )

            if urlparse(absolute).scheme not in (
                "http",
                "https"
            ):
                continue

            links.append({
                "name": label,
                "url": absolute
            })

        # Show forms, since some message applications
        # use forms for inbox navigation.
        forms = []

        for form in soup.find_all("form"):
            forms.append({
                "action": urljoin(
                    str(page.url),
                    form.get("action") or str(page.url)
                ),
                "method": (
                    form.get("method") or "GET"
                ).upper(),
            })

        return {
            "url": str(page.url),
            "title": (
                title.get_text(strip=True)
                if title else None
            ),
            "text": text,
            "links": links,
            "forms": forms,
        }

    def messages_menu(self):
        """
        Discover and navigate message-related pages.
        """

        if not self.message_links:
            self.discover_applications()

        if not self.message_links:
            print(
                "\nCould not automatically discover "
                "the Nachrichten application."
            )

            print(
                "Use the diagnostic option to inspect "
                "the dashboard."
            )

            return

        while True:

            print("\n" + "=" * 60)
            print("NACHRICHTEN")
            print("=" * 60)

            for i, item in enumerate(
                self.message_links,
                1
            ):
                print(
                    f"{i}. {item['name']}"
                )

            print("0. Back")

            choice = input(
                "\nChoose an application: "
            ).strip()

            if choice == "0":
                return

            if not choice.isdigit():
                print("Invalid choice.")
                continue

            index = int(choice) - 1

            if not 0 <= index < len(
                self.message_links
            ):
                print("Invalid choice.")
                continue

            url = self.message_links[index]["url"]

            try:
                result = self.inspect_message_page(url)

                # Navigate to additional links found
                # on the message application page.
                while result["links"]:

                    print("\nPAGE LINKS:")

                    for i, link in enumerate(
                        result["links"],
                        1
                    ):
                        print(
                            f"{i}. {link['name']}"
                        )

                    print("0. Back")

                    choice = input(
                        "\nOpen link: "
                    ).strip()

                    if choice == "0":
                        break

                    if not choice.isdigit():
                        continue

                    index = int(choice) - 1

                    if not 0 <= index < len(
                        result["links"]
                    ):
                        continue

                    try:
                        result = self.inspect_message_page(
                            result["links"][index]["url"]
                        )

                    except Exception as e:
                        print(
                            "Could not open page:",
                            e
                        )

                    input(
                        "\nPress Enter to continue..."
                    )

            except Exception as e:
                print(
                    "\nCould not open Nachrichten:",
                    e
                )

    # --------------------------------------------------------
    # DIAGNOSTICS
    # --------------------------------------------------------

    def inspect_dashboard(self):
        """
        Print all dashboard links.
        Useful for discovering hidden application URLs.
        """

        page = self.dashboard()

        soup = BeautifulSoup(
            page.text,
            "html.parser"
        )

        print("\nDASHBOARD URL:", page.url)

        print("\nAVAILABLE LINKS:\n")

        for a in soup.find_all(
            "a",
            href=True
        ):
            label = a.get_text(
                " ",
                strip=True
            )

            print(
                f"{label[:55]:55} {a['href']}"
            )

        print("\nFORMS:\n")

        for form in soup.find_all("form"):
            print(
                "Action:",
                form.get("action"),
                "| Method:",
                form.get("method")
            )


# ============================================================
# DISPLAY FUNCTIONS
# ============================================================

def print_schedule(sph, day):

    lessons, tt = sph.schedule_for(day)

    week = (
        f" | Woche {tt['week']}"
        if tt.get("week")
        else ""
    )

    print("\n" + "=" * 65)

    print(
        f"STUNDENPLAN — "
        f"{day.strftime('%A, %d.%m.%Y')}{week}"
    )

    print("=" * 65)

    if not lessons:
        print("\nKeine Stunden eingetragen.")
        return

    for les in lessons:

        hours = (
            str(les["from_hour"])
            if les["from_hour"] == les["to_hour"]
            else (
                f"{les['from_hour']}-"
                f"{les['to_hour']}"
            )
        )

        times = (
            f"{les['start']} - {les['end']}"
            if les.get("start")
            else "No time"
        )

        print(
            f"\n{hours:>5} | {times}"
        )

        print(
            f"      {les['name'] or 'Unknown subject'}"
        )

        if les.get("room"):
            print(
                f"      Room: {les['room']}"
            )

        if les.get("teacher"):
            print(
                f"      Teacher: {les['teacher']}"
            )

        if les.get("badge"):
            print(
                f"      Info: {les['badge']}"
            )

        for change in les.get("changes", []):

            print(
                "      >>> SUBSTITUTION: "
                f"{change.get('Art', '-')}: "
                f"{change.get('Hinweis') or change.get('_sprechend') or ''}"
            )

    print("\n" + "=" * 65)


def show_substitutions(sph):

    print("\nFetching substitution plan...")

    try:
        substitutions = sph.substitution_plan()

        if not substitutions:
            print("No substitutions found.")
            return

        for i, sub in enumerate(
            substitutions,
            1
        ):
            print(
                f"\n{i}. {sub.get('Tag_en', 'Unknown date')}"
            )

            print(
                f"   Type: {sub.get('Art', '-')}"
            )

            print(
                f"   Teacher: {sub.get('Lehrerkuerzel', '-')}"
            )

            print(
                f"   Hours: {sub.get('Stunde', '-')}"
            )

            print(
                f"   Information: {sub.get('Hinweis', '-')}"
            )

    except Exception as e:
        print(
            "Could not retrieve substitutions:",
            e
        )


def show_homework(sph):

    print("\nFetching Mein Unterricht...")

    try:
        print(
            "\n" + sph.homework()
        )

    except Exception as e:
        print(
            "Could not retrieve homework:",
            e
        )


# ============================================================
# INTERACTIVE MENU
# ============================================================

def show_menu():

    print("""
╔══════════════════════════════════════════════════════════╗
║                 SCHULPORTAL HESSEN                      ║
║                    LANIS CLIENT                          ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║  1. Tomorrow's schedule                                  ║
║  2. Schedule for a specific date                         ║
║  3. Substitution plan                                     ║
║  4. Nachrichten / Messages                               ║
║  5. Homework / Mein Unterricht                            ║
║  6. Discover portal applications                         ║
║  7. Inspect dashboard (debug)                             ║
║                                                          ║
║  0. Exit                                                  ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
""")


def main():

    required = [
        "SPH_SCHOOL",
        "SPH_USER",
        "SPH_PASS"
    ]

    missing = [
        key for key in required
        if not os.environ.get(key)
    ]

    if missing:
        print(
            "Missing environment variables:",
            ", ".join(missing)
        )
        sys.exit(1)

    sph = SPH(
        os.environ["SPH_SCHOOL"],
        os.environ["SPH_USER"],
        os.environ["SPH_PASS"],
        debug="--debug" in sys.argv
    )

    try:

        print("\nConnecting to Schulportal Hessen...")

        sph.login()

        print("Successfully authenticated!")

        while True:

            show_menu()

            choice = input(
                "Select an option: "
            ).strip()

            try:

                if choice == "1":

                    day = next_school_day()

                    print_schedule(sph, day)

                elif choice == "2":

                    raw = input(
                        "Enter date (DD.MM.YYYY): "
                    ).strip()

                    day = datetime.strptime(
                        raw,
                        "%d.%m.%Y"
                    ).date()

                    print_schedule(sph, day)

                elif choice == "3":

                    show_substitutions(sph)

                elif choice == "4":

                    sph.messages_menu()

                elif choice == "5":

                    show_homework(sph)

                elif choice == "6":

                    sph.discover_applications()

                elif choice == "7":

                    sph.inspect_dashboard()

                elif choice == "0":

                    print("\nGoodbye!")
                    break

                else:

                    print("\nInvalid option.")

            except ValueError:

                print(
                    "\nInvalid date. Use DD.MM.YYYY."
                )

            except SPHError as e:

                print(
                    f"\nSchulportal error: {e}"
                )

            except KeyboardInterrupt:

                print(
                    "\nOperation cancelled."
                )

            except Exception as e:

                print(
                    f"\nUnexpected error: {e}"
                )

            input(
                "\nPress Enter to return to the menu..."
            )

    except SPHError as e:

        print(
            f"\nLogin error: {e}"
        )

    finally:

        sph.close()


if __name__ == "__main__":
    main()
