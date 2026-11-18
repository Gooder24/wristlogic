"""python -m unittest discover tests  (from the repo, with the venv's python)"""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

class FakeWatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        subprocess.run([sys.executable, ROOT / "tests/fake_watch.py", tmp / "watch", "8", "--ill"], check=True)
        cls.env = {**os.environ, "ZDRAVIE_DATA": str(tmp / "data"), "ZDRAVIE_CONFIG": str(tmp / "none.json")}
        cls.out = subprocess.run([sys.executable, ROOT / "zdravie.py", "import", tmp / "watch"], env=cls.env,
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
        # The fake plan: 5 cycles, 22 min awake in 3 runs, 12 min before falling asleep.
        self.assertEqual((n["deep"] // 60, n["rem"] // 60, n["light"] // 60, n["awake"] // 60), (115, 110, 200, 22))
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
        self.assertIn("Hlboký 1 h 55 min", unfolded)

    def test_import_again_adds_nothing(self):
        out = subprocess.run([sys.executable, ROOT / "zdravie.py", "import", Path(self.tmp.name) / "watch"], env=self.env,
                             capture_output=True, text=True, check=True).stdout
        self.assertTrue(out.startswith("Nových súborov 0"), out)

    def test_steps_per_day(self):
        days = {d["date"]: d for d in self.health["days"]}
        self.assertTrue(all(d["steps"] > 10000 for d in list(days.values())[1:-1]))

if __name__ == "__main__":
    unittest.main()
