import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import scheduler as sch  # noqa: E402

# 2026-11-15 is a Sunday (weekday 6)
SUN_9AM = datetime(2026, 11, 15, 9, 0)


class WindowTests(unittest.TestCase):
    def test_weekly_inside_and_outside(self):
        s = {"kind": "weekly", "days": [6], "start_time": "08:00", "end_time": "13:00", "enabled": True}
        self.assertTrue(sch.schedule_active(s, SUN_9AM))
        self.assertFalse(sch.schedule_active(s, datetime(2026, 11, 15, 13, 0)))  # end is exclusive
        self.assertFalse(sch.schedule_active(s, datetime(2026, 11, 14, 9, 0)))   # Saturday

    def test_overnight_window(self):
        s = {"kind": "weekly", "days": [5], "start_time": "22:00", "end_time": "02:00", "enabled": True}
        self.assertTrue(sch.schedule_active(s, datetime(2026, 11, 14, 23, 0)))  # Sat night
        self.assertTrue(sch.schedule_active(s, datetime(2026, 11, 15, 1, 0)))   # Sun early
        self.assertFalse(sch.schedule_active(s, datetime(2026, 11, 15, 3, 0)))

    def test_once(self):
        s = {"kind": "once", "start": "2026-11-15T08:00", "end": "2026-11-15T12:00", "enabled": True}
        self.assertTrue(sch.schedule_active(s, SUN_9AM))
        self.assertFalse(sch.schedule_active({**s, "enabled": False}, SUN_9AM))
        self.assertTrue(sch.schedule_expired(s, datetime(2026, 11, 15, 12, 0)))

    def test_validation(self):
        with self.assertRaises(ValueError):
            sch.validate_schedule({"filename": "a.jpg", "kind": "once",
                                   "start": "2026-11-15T10:00", "end": "2026-11-15T09:00"})
        with self.assertRaises(ValueError):
            sch.validate_schedule({"filename": "../evil.jpg", "kind": "weekly", "days": [1],
                                   "start_time": "08:00", "end_time": "09:00"})
        ok = sch.validate_schedule({"filename": "a.jpg", "kind": "weekly", "days": [6, 6, 0],
                                    "start_time": "8:00", "end_time": "13:00"})
        self.assertEqual(ok["days"], [0, 6])
        self.assertEqual(ok["start_time"], "08:00")


class MoveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.lib, self.live = root / "lib", root / "live"
        self.lib.mkdir(); self.live.mkdir()
        (self.lib / "promo.mp4").write_text("x")
        (self.lib / "untouched.jpg").write_text("x")
        self.store = sch.Store(root / "data")
        self.store.data["settings"].update(library_folder=str(self.lib), live_folder=str(self.live))
        self.store.data["schedules"] = [{"id": "1", "filename": "promo.mp4", "kind": "weekly",
                                         "days": [6], "start_time": "08:00", "end_time": "13:00",
                                         "enabled": True}]

    def tearDown(self):
        self.tmp.cleanup()

    def test_moves_in_and_back(self):
        sch.reconcile(self.store, SUN_9AM)
        self.assertTrue((self.live / "promo.mp4").exists())
        self.assertTrue((self.lib / "untouched.jpg").exists())  # unscheduled files are left alone
        sch.reconcile(self.store, datetime(2026, 11, 15, 14, 0))
        self.assertTrue((self.lib / "promo.mp4").exists())
        self.assertFalse((self.live / "promo.mp4").exists())

    def test_quiet_hours_defer(self):
        self.store.data["settings"].update(quiet_hours_enabled=True, quiet_days=[6],
                                           quiet_start="08:30", quiet_end="12:00")
        sch.reconcile(self.store, SUN_9AM)
        self.assertFalse((self.live / "promo.mp4").exists())
        sch.reconcile(self.store, datetime(2026, 11, 15, 12, 30))  # catches up after quiet hours
        self.assertTrue((self.live / "promo.mp4").exists())

    def test_name_collision_is_not_overwritten(self):
        (self.live / "promo.mp4").write_text("different")
        sch.reconcile(self.store, datetime(2026, 11, 15, 14, 0))  # wants to move live -> lib
        self.assertEqual((self.lib / "promo.mp4").read_text(), "x")
        self.assertEqual((self.live / "promo.mp4").read_text(), "different")
        self.assertEqual(self.store.data["log"][0]["level"], "error")

    def test_overlapping_schedules(self):
        self.store.data["schedules"].append({"id": "2", "filename": "promo.mp4", "kind": "once",
                                             "start": "2026-11-15T12:00", "end": "2026-11-15T18:00",
                                             "enabled": True})
        sch.reconcile(self.store, SUN_9AM)
        sch.reconcile(self.store, datetime(2026, 11, 15, 14, 0))  # weekly ended, once still active
        self.assertTrue((self.live / "promo.mp4").exists())


if __name__ == "__main__":
    unittest.main()
