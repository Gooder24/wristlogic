"""Writes FIT files shaped like a Garmin watch's (Sleep/, Monitor/) for a few synthetic nights.

    python tests/fake_watch.py OUT_DIR [NIGHTS] [--ill]
"""
import random, sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.monitoring_message import MonitoringMessage
from fit_tool.profile.messages.respiration_rate_message import RespirationRateMessage
from fit_tool.profile.messages.sleep_assessment_message import SleepAssessmentMessage
from fit_tool.profile.messages.sleep_level_message import SleepLevelMessage
from fit_tool.profile.messages.stress_level_message import StressLevelMessage
from fit_tool.profile.profile_type import ActivityType, FileType, Manufacturer, SleepLevel

TZ = ZoneInfo("Europe/Bratislava")
FIT_EPOCH = 631065600

def builder(kind):
    b = FitFileBuilder(auto_define=True)
    f = FileIdMessage(); f.type = kind; f.manufacturer = Manufacturer.GARMIN.value; f.product = 3888; f.serial_number = 3400000000
    b.add(f)
    return b

def night(day, ill):
    """Bed 22:45 -> 06:45 local of the morning `day`, one sample a minute."""
    rnd = random.Random(day.toordinal())
    start = datetime(day.year, day.month, day.day, 6, 45, tzinfo=TZ) - timedelta(hours=8, minutes=rnd.randint(-40, 40))
    levels, t = [], start
    plan = [SleepLevel.AWAKE] * 12
    for cycle in range(5):
        plan += [SleepLevel.LIGHT] * 25 + [SleepLevel.DEEP] * (35 - cycle * 6) + [SleepLevel.LIGHT] * 15 + [SleepLevel.REM] * (10 + cycle * 6)
        if cycle == 2: plan += [SleepLevel.AWAKE] * 8
    plan += [SleepLevel.AWAKE] * 6
    b = builder(FileType.SLEEP if hasattr(FileType, "SLEEP") else 49)
    for i, lv in enumerate(plan):
        m = SleepLevelMessage(); m.timestamp = int((start + timedelta(minutes=i)).timestamp() * 1000); m.sleep_level = lv
        b.add(m)
    a = SleepAssessmentMessage(); a.overall_sleep_score = 70 + rnd.randint(0, 20); a.sleep_quality_score = 75; a.sleep_recovery_score = 60
    b.add(a)
    end = start + timedelta(minutes=len(plan))
    # Monitoring of that night and the following day: heart rate every 2 minutes, steps by day.
    mb = builder(FileType.MONITORING_B)
    t, steps, base = start - timedelta(hours=1), 0, 58 + (6 if ill else 0)
    last_full, i = None, 0
    while t < end + timedelta(hours=14):
        asleep = start < t < end
        hr = (base - 6 + rnd.randint(-2, 2)) if asleep else (75 + rnd.randint(-10, 30))
        m = MonitoringMessage()
        fit_ts = int(t.timestamp()) - FIT_EPOCH
        if last_full is None or fit_ts - last_full > 3600:
            m.timestamp = int(t.timestamp() * 1000); last_full = fit_ts
        else:
            m.timestamp_16 = fit_ts & 0xFFFF
        m.heart_rate = hr
        if not asleep:
            steps += rnd.randint(0, 120)
            m.activity_type = ActivityType.WALKING; m.cycles = steps
        mb.add(m)
        if asleep and i % 2 == 0:
            s = StressLevelMessage(); s.stress_level_time = int(t.timestamp() * 1000); s.stress_level_value = 15 + rnd.randint(0, 8)
            mb.add(s)
            r = RespirationRateMessage(); r.timestamp = int(t.timestamp() * 1000); r.respiration_rate = (14.5 + (2.5 if ill else 0) + rnd.random())
            mb.add(r)
        t += timedelta(minutes=2); i += 1
    return b.build(), mb.build()

if __name__ == "__main__":
    out = Path(sys.argv[1]); count = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 7
    ill = "--ill" in sys.argv
    today = datetime.now(TZ).date()
    (out / "GARMIN/Sleep").mkdir(parents=True, exist_ok=True); (out / "GARMIN/Monitor").mkdir(parents=True, exist_ok=True)
    for k in range(count, 0, -1):
        day = today - timedelta(days=k - 1)
        sleep, mon = night(day, ill and k == 1)
        sleep.to_file(str(out / f"GARMIN/Sleep/S{day:%m%d}.fit")); mon.to_file(str(out / f"GARMIN/Monitor/M{day:%m%d}.FIT"))
