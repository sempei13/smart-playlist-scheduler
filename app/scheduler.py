"""Schedule logic and the file mover.

The scheduler works on *desired state*, not one-off events: once a minute it
asks "should this file be in the Live folder right now?" for every scheduled
file, then moves anything that is in the wrong place. That means:

* If the Mac was asleep or off at a scheduled time, the move happens as soon
  as the app is running again.
* Overlapping schedules for the same file just work (live if ANY is active).
* Files that have no schedule are never touched.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import uuid
from datetime import datetime, time, timedelta
from pathlib import Path

MEDIA_EXTENSIONS = {
    # images
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".webp",
    # video
    ".mov", ".mp4", ".m4v", ".avi", ".mkv", ".mpg", ".mpeg", ".wmv", ".webm",
}

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

DEFAULT_SETTINGS = {
    "library_folder": "",
    "live_folder": "",
    "quiet_hours_enabled": False,
    "quiet_start": "09:00",  # no moves between these times (e.g. during service)
    "quiet_end": "12:00",
    "quiet_days": [6],       # 0=Mon ... 6=Sun
}


def _parse_hhmm(value: str) -> time:
    hours, minutes = value.split(":")[:2]
    return time(int(hours), int(minutes))


def _parse_dt(value: str) -> datetime:
    # Accepts "2026-11-15T08:00" (what <input type=datetime-local> sends)
    return datetime.fromisoformat(value)


def in_daily_window(now: datetime, days: list[int], start: str, end: str) -> bool:
    """True if `now` falls in a window that opens at `start` on any of `days`.

    If end <= start the window runs past midnight into the next day
    (e.g. Sat 22:00 -> Sun 02:00 when days=[5]).
    """
    start_t, end_t = _parse_hhmm(start), _parse_hhmm(end)
    overnight = end_t <= start_t
    # A window may have opened today, or (if overnight) yesterday.
    for offset in (0, 1) if overnight else (0,):
        open_day = (now - timedelta(days=offset)).date()
        if open_day.weekday() not in days:
            continue
        opens = datetime.combine(open_day, start_t)
        closes = datetime.combine(open_day + timedelta(days=1 if overnight else 0), end_t)
        if opens <= now < closes:
            return True
    return False


def schedule_active(schedule: dict, now: datetime) -> bool:
    if not schedule.get("enabled", True):
        return False
    if schedule["kind"] == "once":
        return _parse_dt(schedule["start"]) <= now < _parse_dt(schedule["end"])
    if schedule["kind"] == "weekly":
        return in_daily_window(now, schedule["days"], schedule["start_time"], schedule["end_time"])
    return False


def schedule_expired(schedule: dict, now: datetime) -> bool:
    return schedule["kind"] == "once" and _parse_dt(schedule["end"]) <= now


def in_quiet_hours(settings: dict, now: datetime) -> bool:
    if not settings.get("quiet_hours_enabled"):
        return False
    return in_daily_window(now, settings.get("quiet_days", []),
                           settings["quiet_start"], settings["quiet_end"])


def validate_schedule(data: dict) -> dict:
    """Clean up a schedule submitted from the UI. Raises ValueError if invalid."""
    filename = str(data.get("filename", "")).strip()
    if not filename or "/" in filename or filename.startswith("."):
        raise ValueError("Pick a file.")
    kind = data.get("kind")
    out = {"id": data.get("id") or uuid.uuid4().hex[:10], "filename": filename,
           "kind": kind, "enabled": bool(data.get("enabled", True)),
           "note": str(data.get("note", "")).strip()[:200]}
    if kind == "once":
        try:
            start, end = _parse_dt(data["start"]), _parse_dt(data["end"])
        except (KeyError, ValueError):
            raise ValueError("Enter a start and end date/time.")
        if end <= start:
            raise ValueError("The end time must be after the start time.")
        out["start"], out["end"] = start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes")
    elif kind == "weekly":
        days = sorted({int(d) for d in data.get("days", []) if 0 <= int(d) <= 6})
        if not days:
            raise ValueError("Pick at least one day.")
        try:
            st, et = _parse_hhmm(data["start_time"]), _parse_hhmm(data["end_time"])
        except (KeyError, ValueError):
            raise ValueError("Enter a start and end time.")
        if st == et:
            raise ValueError("Start and end time can't be the same.")
        out["days"], out["start_time"], out["end_time"] = days, st.strftime("%H:%M"), et.strftime("%H:%M")
    else:
        raise ValueError("Choose one-time or weekly.")
    return out


def describe(schedule: dict) -> str:
    if schedule["kind"] == "once":
        s, e = _parse_dt(schedule["start"]), _parse_dt(schedule["end"])
        fmt = "%a %b %-d, %-I:%M %p"
        return f"{s.strftime(fmt)} → {e.strftime(fmt)}"
    days = ", ".join(DAY_NAMES[d] for d in schedule["days"])
    st = datetime.combine(datetime.today(), _parse_hhmm(schedule["start_time"])).strftime("%-I:%M %p")
    et = datetime.combine(datetime.today(), _parse_hhmm(schedule["end_time"])).strftime("%-I:%M %p")
    return f"Every {days}, {st} → {et}"


class Store:
    """Settings, schedules and the activity log, saved as JSON."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "data.json"
        self.lock = threading.RLock()
        self.data = {"settings": dict(DEFAULT_SETTINGS), "schedules": [], "tests": {}, "log": []}
        if self.path.exists():
            loaded = json.loads(self.path.read_text())
            self.data["settings"].update(loaded.get("settings", {}))
            self.data["schedules"] = loaded.get("schedules", [])
            self.data["tests"] = loaded.get("tests", {})  # so a restart mid-test still ends it
            self.data["log"] = loaded.get("log", [])

    def save(self):
        with self.lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2))
            os.replace(tmp, self.path)

    def log(self, message: str, level: str = "info"):
        with self.lock:
            self.data["log"].insert(0, {"time": datetime.now().isoformat(timespec="seconds"),
                                        "level": level, "message": message})
            del self.data["log"][300:]
            self.save()


def list_media(folder: str) -> list[str]:
    if not folder or not os.path.isdir(folder):
        return []
    return sorted((f for f in os.listdir(folder)
                   if not f.startswith(".") and Path(f).suffix.lower() in MEDIA_EXTENSIONS
                   and os.path.isfile(os.path.join(folder, f))), key=str.lower)


def reconcile(store: Store, now: datetime | None = None) -> list[str]:
    """Move every scheduled file to where it should be right now."""
    now = now or datetime.now()
    actions: list[str] = []
    with store.lock:
        settings = store.data["settings"]
        library, live = settings["library_folder"], settings["live_folder"]
        if not (library and live and os.path.isdir(library) and os.path.isdir(live)):
            return actions
        if os.path.realpath(library) == os.path.realpath(live):
            return actions
        quiet = in_quiet_hours(settings, now)

        should_be_live: dict[str, bool] = {}
        for sched in store.data["schedules"]:
            name = sched["filename"]
            should_be_live[name] = should_be_live.get(name, False) or schedule_active(sched, now)

        # Tests (the "Test" button) put a file in the playlist briefly, then take it back
        # out. They were started by a person on purpose, so quiet hours don't block them.
        tests = store.data.setdefault("tests", {})
        ended_tests = [n for n, until in tests.items() if _parse_dt(until) <= now]
        for name in tests:
            if name not in ended_tests:
                should_be_live[name] = True
            else:
                should_be_live.setdefault(name, False)

        for name, want_live in should_be_live.items():
            if quiet and name not in tests:
                continue
            if name in ended_tests:
                del tests[name]
                store.save()
            src_dir, dst_dir = (library, live) if want_live else (live, library)
            src, dst = os.path.join(src_dir, name), os.path.join(dst_dir, name)
            if not os.path.exists(src):
                continue  # already where it belongs (or missing; reported in the UI)
            if os.path.exists(dst):
                msg = (f"Couldn't move “{name}”: a file with that name is already in "
                       f"the {'Live' if want_live else 'Library'} folder.")
                if not store.data["log"] or store.data["log"][0]["message"] != msg:
                    store.log(msg, "error")
                continue
            try:
                shutil.move(src, dst)
            except OSError as exc:
                store.log(f"Couldn't move “{name}”: {exc}", "error")
                continue
            msg = (f"Added “{name}” to the playlist" if want_live
                   else f"Removed “{name}” from the playlist")
            store.log(msg)
            actions.append(msg)
    return actions


def start_test(store: Store, filename: str, seconds: int, now: datetime | None = None):
    """Put `filename` in the playlist now and take it back out after `seconds`."""
    now = now or datetime.now()
    seconds = max(5, min(int(seconds), 3600))
    with store.lock:
        if filename not in list_media(store.data["settings"]["library_folder"]) + \
                list_media(store.data["settings"]["live_folder"]):
            raise ValueError(f"“{filename}” isn't in the Library folder.")
        until = now + timedelta(seconds=seconds)
        store.data.setdefault("tests", {})[filename] = until.isoformat(timespec="seconds")
        store.save()
    store.log(f"Test started: “{filename}” goes into the playlist for {seconds} seconds")
    reconcile(store, now)


def stop_test(store: Store, filename: str, now: datetime | None = None):
    now = now or datetime.now()
    with store.lock:
        tests = store.data.setdefault("tests", {})
        if filename not in tests:
            return
        tests[filename] = now.isoformat(timespec="seconds")
        store.save()
    store.log(f"Test ended early for “{filename}”")
    reconcile(store, now)


def test_seconds_left(store: Store, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now()
    return {name: max(0, int((_parse_dt(until) - now).total_seconds()))
            for name, until in store.data.get("tests", {}).items()}


def cleanup_expired(store: Store, now: datetime | None = None, keep_days: int = 7):
    """Delete one-time schedules that ended over `keep_days` ago (after their file went back)."""
    now = now or datetime.now()
    with store.lock:
        before = len(store.data["schedules"])
        store.data["schedules"] = [
            s for s in store.data["schedules"]
            if not (schedule_expired(s, now) and _parse_dt(s["end"]) < now - timedelta(days=keep_days))
        ]
        if len(store.data["schedules"]) != before:
            store.save()


def run_forever(store: Store, stop: threading.Event, interval: int = 30):
    while not stop.is_set():
        try:
            reconcile(store)
            cleanup_expired(store)
        except Exception as exc:  # keep the loop alive no matter what
            store.log(f"Scheduler error: {exc}", "error")
        stop.wait(interval)
