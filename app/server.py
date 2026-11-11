"""Smart Playlist Scheduler: a small local web app.

Run:  python3 app/server.py         then open http://localhost:8765
Uses only the Python standard library, so nothing else needs installing.
"""

from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).parent))
import scheduler as sch  # noqa: E402

HOST = os.environ.get("SPS_HOST", "127.0.0.1")
PORT = int(os.environ.get("SPS_PORT", "8765"))
DATA_DIR = Path(os.environ.get(
    "SPS_DATA_DIR", Path.home() / "Library" / "Application Support" / "SmartPlaylistScheduler"))
STATIC = Path(__file__).parent / "static"

store = sch.Store(DATA_DIR)


def state() -> dict:
    now = datetime.now()
    with store.lock:
        settings = store.data["settings"]
        library, live = settings["library_folder"], settings["live_folder"]
        lib_files, live_files = sch.list_media(library), sch.list_media(live)
        schedules = []
        for s in store.data["schedules"]:
            name = s["filename"]
            where = "live" if name in live_files else "library" if name in lib_files else "missing"
            schedules.append({**s, "description": sch.describe(s),
                              "active": sch.schedule_active(s, now),
                              "expired": sch.schedule_expired(s, now),
                              "location": where})
        return {
            "now": now.isoformat(timespec="seconds"),
            "settings": settings,
            "folders_ok": bool(library and live and os.path.isdir(library) and os.path.isdir(live)
                               and os.path.realpath(library) != os.path.realpath(live)),
            "quiet_now": sch.in_quiet_hours(settings, now),
            "library_files": lib_files,
            "live_files": live_files,
            "schedules": schedules,
            "tests": sch.test_seconds_left(store, now),
            "log": store.data["log"][:100],
        }


def choose_folder(prompt: str) -> str | None:
    """Open the native macOS folder picker."""
    script = f'POSIX path of (choose folder with prompt "{prompt}")'
    try:
        out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=600)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:  # user pressed Cancel
        return None
    return out.stdout.strip().rstrip("/") or None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep the terminal quiet
        pass

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def _file(self, path: Path):
        if not path.is_file():
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        size = path.stat().st_size
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):  # lets the browser preview videos
            a, _, b = rng[6:].partition("-")
            start = int(a) if a else max(0, size - int(b))
            end = int(b) if a and b else size - 1
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with open(path, "rb") as fh:
            fh.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = fh.read(min(1 << 16, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                remaining -= len(chunk)

    def _same_origin(self) -> bool:
        # Block other websites from driving this app through your browser.
        origin = self.headers.get("Origin")
        return origin is None or urlparse(origin).netloc == self.headers.get("Host")

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            return self._file(STATIC / "index.html")
        if url.path == "/api/state":
            return self._json(state())
        if url.path == "/media":
            q = parse_qs(url.query)
            name = unquote(q.get("name", [""])[0])
            where = q.get("where", ["library"])[0]
            settings = store.data["settings"]
            folder = settings["live_folder"] if where == "live" else settings["library_folder"]
            if not folder or "/" in name or name.startswith("."):
                return self.send_error(404)
            return self._file(Path(folder) / name)
        self.send_error(404)

    def do_POST(self):
        if not self._same_origin():
            return self.send_error(403)
        url = urlparse(self.path)
        try:
            data = self._body()
        except json.JSONDecodeError:
            return self._json({"error": "Bad request"}, 400)

        if url.path == "/api/choose-folder":
            which = data.get("which")
            if which not in ("library_folder", "live_folder"):
                return self._json({"error": "Unknown folder"}, 400)
            prompt = ("Choose your media Library folder" if which == "library_folder"
                      else "Choose the folder your ProPresenter Smart Playlist watches")
            path = choose_folder(prompt)
            if path:
                with store.lock:
                    store.data["settings"][which] = path
                    store.save()
            return self._json(state())

        if url.path == "/api/settings":
            with store.lock:
                s = store.data["settings"]
                for key in ("library_folder", "live_folder"):
                    if key in data:
                        s[key] = str(data[key]).strip().rstrip("/")
                if "quiet_hours_enabled" in data:
                    s["quiet_hours_enabled"] = bool(data["quiet_hours_enabled"])
                try:
                    for key in ("quiet_start", "quiet_end"):
                        if key in data:
                            s[key] = sch._parse_hhmm(data[key]).strftime("%H:%M")
                    if "quiet_days" in data:
                        s["quiet_days"] = sorted({int(d) for d in data["quiet_days"] if 0 <= int(d) <= 6})
                except ValueError:
                    return self._json({"error": "Enter valid quiet-hours times."}, 400)
                store.save()
            sch.reconcile(store)
            return self._json(state())

        if url.path == "/api/schedules":
            try:
                schedule = sch.validate_schedule(data)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
            with store.lock:
                existing = [i for i, s in enumerate(store.data["schedules"]) if s["id"] == schedule["id"]]
                old_name = store.data["schedules"][existing[0]]["filename"] if existing else None
                settings = store.data["settings"]
                available = (sch.list_media(settings["library_folder"])
                             + sch.list_media(settings["live_folder"]))
                if schedule["filename"] != old_name and schedule["filename"] not in available:
                    return self._json({"error": "That file isn't in the Library folder any more."}, 400)
                if existing:
                    store.data["schedules"][existing[0]] = schedule
                else:
                    store.data["schedules"].append(schedule)
                store.save()
            if old_name and old_name != schedule["filename"]:
                store.log(f"Schedule switched from “{old_name}” to “{schedule['filename']}”")
            store.log(f"Saved schedule for “{schedule['filename']}”: {sch.describe(schedule)}")
            sch.reconcile(store)
            return self._json(state())

        if url.path == "/api/schedules/delete":
            with store.lock:
                sid = data.get("id")
                gone = [s for s in store.data["schedules"] if s["id"] == sid]
                store.data["schedules"] = [s for s in store.data["schedules"] if s["id"] != sid]
                store.save()
            if gone:
                store.log(f"Deleted schedule for “{gone[0]['filename']}”")
            sch.reconcile(store)
            return self._json(state())

        if url.path == "/api/schedules/toggle":
            with store.lock:
                for s in store.data["schedules"]:
                    if s["id"] == data.get("id"):
                        s["enabled"] = not s.get("enabled", True)
                store.save()
            sch.reconcile(store)
            return self._json(state())

        if url.path == "/api/test":
            name, seconds = str(data.get("filename", "")), data.get("seconds", 30)
            try:
                sch.start_test(store, name, int(seconds))
            except (ValueError, TypeError) as exc:
                return self._json({"error": str(exc) or "Couldn't start the test."}, 400)
            # end the test right on time instead of waiting for the next 30-second check
            threading.Timer(max(5, min(int(seconds), 3600)) + 0.5, sch.reconcile, args=(store,)).start()
            return self._json(state())

        if url.path == "/api/test/stop":
            sch.stop_test(store, str(data.get("filename", "")))
            return self._json(state())

        if url.path == "/api/run-now":
            sch.reconcile(store)
            return self._json(state())

        self.send_error(404)


def main():
    stop = threading.Event()
    threading.Thread(target=sch.run_forever, args=(store, stop), daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"Smart Playlist Scheduler running at {url}  (Ctrl+C to stop)")
    if "--open" in sys.argv:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
