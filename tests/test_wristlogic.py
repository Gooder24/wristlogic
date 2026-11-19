"""python -m unittest discover tests  (from the repo, with the venv's python)"""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["WEFT_CALENDAR"] = ""  # never Karchi's live Weft calendar

class FakeWatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        subprocess.run([sys.executable, ROOT / "tests/fake_watch.py", tmp / "watch", "8", "--ill"], check=True)
        cls.env = {**os.environ, "WEFT_CALENDAR": "", "WRISTLOGIC_DATA": str(tmp / "data"), "WRISTLOGIC_CONFIG": str(tmp / "none.json")}
        cls.out = subprocess.run([sys.executable, ROOT / "wristlogic.py", "import", tmp / "watch"], env=cls.env,
                                 capture_output=True, text=True, check=True).stdout
        cls.health = json.loads((tmp / "data/public/health.json").read_text())
        cls.ics = (tmp / "data/public/spanok.ics").read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_night_with_its_stages(self):
        nights = self.health["nights"]
        self.assertEqual(len(nights), 8)
        n = nights[0]
        # The fake plan: 5 cycles, 26 min awake in 3 runs, 12 min before falling asleep.
        self.assertEqual((n["deep"] // 60, n["rem"] // 60, n["light"] // 60, n["awake"] // 60), (115, 110, 200, 26))
        self.assertEqual(n["awakenings"], 1)
        self.assertEqual(n["onset"] - n["start"], 12 * 60)

    def test_sleep_heart_rate_lines_up_with_the_sleep(self):
        # Monitoring uses 16-bit timestamps: a wrong reconstruction puts daytime pulse into the night.
        for n in self.health["nights"][:-1]:
            self.assertLess(n["rhr"], 56)

    def test_recovery_needs_a_baseline_and_reads_the_last_night_as_ill(self):
        nights = self.health["nights"]
        self.assertTrue(all(n["recovery"] is None for n in nights[:4]))
        self.assertTrue(all(n["recovery"] is not None for n in nights[4:]))
        self.assertTrue(nights[-1]["ill"])
        self.assertFalse(any(n["ill"] for n in nights[:-1]))
        self.assertLess(nights[-1]["recovery"], min(n["recovery"] for n in nights[4:-1]))

    def test_calendar_feed(self):
        text = self.ics.decode()
        self.assertEqual(text.count("BEGIN:VEVENT"), 8)
        self.assertIn("X-WR-CALNAME:Spánok", text)
        self.assertTrue(all(len(line) <= 75 for line in self.ics.split(b"\r\n")))
        unfolded = text.replace("\r\n ", "")
        self.assertIn("Fázy: hlboký 1 h 55 min (27 %) · ľahký 3 h 20 min (47 %) · REM 1 h 50 min (26 %)", unfolded)
        self.assertIn("Priebeh: ", unfolded)

    def test_import_again_adds_nothing(self):
        out = subprocess.run([sys.executable, ROOT / "wristlogic.py", "import", Path(self.tmp.name) / "watch"], env=self.env,
                             capture_output=True, text=True, check=True).stdout
        self.assertTrue(out.startswith("Nových súborov 0"), out)

    def test_steps_per_day(self):
        days = {d["date"]: d for d in self.health["days"]}
        self.assertTrue(all(d["steps"] > 10000 for d in list(days.values())[1:-1]))

if __name__ == "__main__":
    unittest.main()

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.monitoring_info_message import MonitoringInfoMessage
from fit_tool.profile.messages.monitoring_message import MonitoringMessage
from fit_tool.profile.messages.sleep_assessment_message import SleepAssessmentMessage
from fit_tool.profile.messages.sleep_level_message import SleepLevelMessage
from fit_tool.profile.messages.event_message import EventMessage
from fit_tool.profile.profile_type import EventType, SleepLevel
import fitimport, metrics, wristlogic

TZ = ZoneInfo("Europe/Bratislava")

def at(day, hh, mm=0):
    return datetime(2026, 11, day, hh, mm, tzinfo=TZ)

def sleep_file(path, stages, assessment=None, window=None):
    """stages: [(datetime, SleepLevel)], written as Garmin's change records; window: (start, stop) events."""
    b = FitFileBuilder(auto_define=True)
    if window:
        for t, kind in zip(window, (EventType.START, EventType.STOP)):
            e = EventMessage(); e.timestamp = int(t.timestamp() * 1000); e.event = 74; e.event_type = kind; b.add(e)
    for t, lv in stages:
        m = SleepLevelMessage(); m.timestamp = int(t.timestamp() * 1000); m.sleep_level = lv; b.add(m)
    if assessment:
        a = SleepAssessmentMessage()
        for k, v in assessment.items(): setattr(a, k, v)
        b.add(a)
    b.build().to_file(str(path))

class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.dir = Path(self.tmp.name)
        self.db = fitimport.connect(self.dir / "z.db")

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, *names):
        fitimport.import_files(self.db, [(self.dir / n, n) for n in names])
        return metrics.sleeps(self.db)

class Edges(Base):
    def test_instinct_2_records_name_the_time_before_them(self):
        # The Instinct 2's shape: a window, and each record ending the stretch it names, the last on the stop.
        sleep_file(self.dir / "a.fit", [(at(10, 23), SleepLevel.LIGHT), (at(11, 0), SleepLevel.DEEP),
                                        (at(11, 0, 10), SleepLevel.AWAKE), (at(11, 1), SleepLevel.REM)],
                   window=(at(10, 22, 48), at(11, 1)))
        [s] = self.load("a.fit")
        self.assertEqual((s["light"], s["deep"], s["awake"], s["rem"]), (12 * 60, 3600, 600, 50 * 60))
        self.assertEqual((s["start"], s["end"], s["wake"]), (int(at(10, 22, 48).timestamp()), int(at(11, 1).timestamp()), int(at(11, 1).timestamp())))
        self.assertEqual(s["awakenings"], 1)

    def instinct_night(self):
        sleep_file(self.dir / "a.fit", [(at(10, 23), SleepLevel.LIGHT), (at(11, 0), SleepLevel.DEEP),
                                        (at(11, 0, 10), SleepLevel.AWAKE), (at(11, 1), SleepLevel.REM)],
                   window=(at(10, 22, 48), at(11, 1)))
        self.load("a.fit")
        return metrics.nights(self.db)

    def test_stages_with_their_share_and_the_course_of_the_night(self):
        [n] = self.instinct_night()
        self.assertEqual(wristlogic.stage_lines(n), [
            "Fázy: hlboký 1 h 00 min (49 %) · ľahký 12 min (10 %) · REM 50 min (41 %) · bdenie 10 min (1× prebudený)",
            "Priebeh: 22:48 ľahký 12 min → 23:00 hlboký 1 h 00 min → 00:00 bdenie 10 min → 00:10 REM 50 min"])

    def test_a_dense_night_keeps_a_short_course(self):
        n = {"deep": 0, "light": 0, "rem": 0, "awake": 0, "asleep": 1, "awakenings": 0,
             "spans": [(60 * i, 2 + i % 3, 60) for i in range(300)]}
        course = wristlogic.stage_lines(n)[1].split(" → ")
        self.assertLessEqual(len(course), wristlogic.RUNS)

    @unittest.skipUnless((ROOT.parent / "weft/server/calendar/kalendar.py").exists(), "needs Weft's kalendar.py beside this repo")
    def test_the_calendar_lands_in_weft_and_keeps_karchis_settings(self):
        weft = self.dir / "weft"; (weft / "data").mkdir(parents=True)
        (weft / "kalendar.py").write_bytes((ROOT.parent / "weft/server/calendar/kalendar.py").read_bytes())
        mine = {"id": "kx-1", "name": "Moje", "events": [{"uid": "a", "title": "t", "start": "2026-11-01T10:00:00.000Z", "end": "2026-11-01T11:00:00.000Z"}]}
        (weft / "data/calendars.json").write_text(json.dumps({"schema": 2, "calendars": [mine]}))
        wristlogic.WEFT = str(weft)
        try:
            nights = self.instinct_night()
            self.assertIsNone(wristlogic.to_weft(nights, []))
            doc = json.loads((weft / "data/calendars.json").read_text())
            self.assertEqual(doc["calendars"][0], mine)
            cal = doc["calendars"][1]
            self.assertEqual((cal["id"], cal["name"], len(cal["events"])), (wristlogic.CAL_ID, "Spánok", 1))
            self.assertIn("Fázy: hlboký 1 h 00 min", cal["events"][0]["description"])
            # Karchi hides it in Weft; the next import changes the nights and keeps it hidden.
            cal["visible"] = False
            (weft / "data/calendars.json").write_text(json.dumps(doc))
            self.assertIsNone(wristlogic.to_weft([], []))
            doc = json.loads((weft / "data/calendars.json").read_text())
            self.assertEqual((doc["calendars"][1]["visible"], doc["calendars"][1]["events"]), (False, []))
            # Kalendarix's old subscription to the feed comes in from x270: the next run takes it out, nothing else.
            doc["calendars"].append({"id": "kx-sub", "name": "Spánok", "sourceUrl": wristlogic.FEED, "events": []})
            (weft / "data/calendars.json").write_text(json.dumps(doc))
            self.assertIsNone(wristlogic.to_weft())
            after = json.loads((weft / "data/calendars.json").read_text())
            self.assertEqual([c["id"] for c in after["calendars"]], ["kx-1", wristlogic.CAL_ID])
            self.assertEqual(after["calendars"][1]["visible"], False)
        finally:
            wristlogic.WEFT = ""

    def test_change_records_keep_their_whole_length(self):
        sleep_file(self.dir / "a.fit", [(at(10, 23), SleepLevel.LIGHT), (at(11, 0), SleepLevel.DEEP),
                                        (at(11, 1), SleepLevel.REM), (at(11, 2), SleepLevel.AWAKE)])
        [s] = self.load("a.fit")
        self.assertEqual((s["light"], s["deep"], s["rem"]), (3600, 3600, 3600))
        self.assertEqual(s["wake"], int(at(11, 2).timestamp()))
        self.assertTrue(s["main"])

    def test_a_nap_before_the_night_stays_apart_and_a_partial_night_is_a_night(self):
        sleep_file(self.dir / "nap.fit", [(at(10, 20, 0), SleepLevel.LIGHT), (at(10, 20, 25), SleepLevel.AWAKE)])
        sleep_file(self.dir / "night.fit", [(at(10, 21, 30), SleepLevel.LIGHT), (at(11, 5), SleepLevel.AWAKE)])
        sleep_file(self.dir / "part.fit", [(at(12, 22), SleepLevel.LIGHT), (at(13, 0), SleepLevel.AWAKE)])
        nap, night, part = self.load("nap.fit", "night.fit", "part.fit")
        self.assertEqual(nap["asleep"], 25 * 60)
        self.assertFalse(nap["main"])
        self.assertTrue(night["main"] and part["main"])

    def test_a_newer_version_of_a_file_replaces_the_older(self):
        sleep_file(self.dir / "v1.fit", [(at(10, 23), SleepLevel.LIGHT), (at(11, 5, 20), SleepLevel.AWAKE)])
        sleep_file(self.dir / "v2.fit", [(at(10, 23), SleepLevel.LIGHT), (at(11, 4), SleepLevel.AWAKE)])
        fitimport.import_files(self.db, [(self.dir / "v1.fit", "Sleep/S.fit")])
        fitimport.import_files(self.db, [(self.dir / "v2.fit", "Sleep/S.fit")])
        [s] = metrics.sleeps(self.db)
        self.assertEqual(s["wake"], int(at(11, 4).timestamp()))

    def test_partial_garmin_scores_still_publish(self):
        sleep_file(self.dir / "a.fit", [(at(10, 23), SleepLevel.LIGHT), (at(11, 6), SleepLevel.AWAKE)],
                   {"overall_sleep_score": 80, "sleep_quality_score": 70})
        self.load("a.fit")
        nights, days = metrics.nights(self.db), []
        text = wristlogic.ics(nights, days)
        self.assertIn("Garmin skóre spánku 80 (kvalita 70)", text.replace("\r\n ", ""))

    def test_monitoring_offsets_from_a_monitoring_info_anchor(self):
        b = FitFileBuilder(auto_define=True)
        t0 = int(at(10, 12).timestamp())
        i = MonitoringInfoMessage(); i.timestamp = t0 * 1000; b.add(i)
        for k in range(1, 4):
            m = MonitoringMessage(); m.timestamp_16 = (t0 - fitimport.FIT_EPOCH + 60 * k) & 0xFFFF; m.heart_rate = 60 + k; b.add(m)
        b.build().to_file(str(self.dir / "m.fit"))
        self.load("m.fit")
        self.assertEqual(metrics.series(self.db, "hr"), [(t0 + 60, 61.0), (t0 + 120, 62.0), (t0 + 180, 63.0)])

class Formats(Base):
    def dense(self, path, minutes):
        """minutes: [(datetime, SleepLevel, count)] written one record a minute."""
        stages = []
        for t, lv, n in minutes:
            stages += [(t + timedelta(minutes=k), lv) for k in range(n)]
        sleep_file(path, stages)

    def test_dense_off_wrist_gap_is_not_sleep(self):
        self.dense(self.dir / "a.fit", [(at(10, 23), SleepLevel.LIGHT, 120), (at(11, 2), SleepLevel.LIGHT, 180)])
        sleeps = self.load("a.fit")
        self.assertEqual(sum(s["asleep"] for s in sleeps), 300 * 60)

    def test_dense_nap_in_the_same_file_stays_apart(self):
        self.dense(self.dir / "a.fit", [(at(10, 20), SleepLevel.LIGHT, 25), (at(10, 21, 30), SleepLevel.LIGHT, 420)])
        nap, night = self.load("a.fit")
        self.assertEqual(nap["asleep"], 25 * 60)
        self.assertFalse(nap["main"])

    def test_sparse_night_across_two_files(self):
        sleep_file(self.dir / "a.fit", [(at(10, 23), SleepLevel.LIGHT), (at(11, 0), SleepLevel.DEEP)])
        sleep_file(self.dir / "b.fit", [(at(11, 1), SleepLevel.REM), (at(11, 2), SleepLevel.AWAKE)])
        [s] = self.load("a.fit", "b.fit")
        self.assertEqual(s["asleep"], 3 * 3600)

    def test_equal_fragments_make_one_night(self):
        sleep_file(self.dir / "a.fit", [(at(10, 22), SleepLevel.LIGHT), (at(10, 23), SleepLevel.AWAKE)])
        sleep_file(self.dir / "b.fit", [(at(11, 1), SleepLevel.LIGHT), (at(11, 2), SleepLevel.AWAKE)])
        a, b = self.load("a.fit", "b.fit")
        self.assertEqual([a["main"], b["main"]].count(True), 1)
