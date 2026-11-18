"""Garmin FIT files -> rows in zdravie.db.

Every file the watch had is kept under fit/ (the watch deletes sleep and monitoring files after a Garmin
Connect sync and when its memory fills), and its messages become time series in `samples`:

    hr        heart rate, bpm (all-day monitoring and activity records)
    sleep     sleep level: 0 unmeasurable, 1 awake, 2 light, 3 deep, 4 REM (Garmin's own staging)
    stress    Garmin stress 0-100 (derived by the watch from HRV)
    resp      respiration rate, breaths/min
    spo2      pulse oximetry, %
    hrv       overnight HRV (ms), when the watch reports it
    rhr       Garmin's resting heart rate of the day
    vo2max    Garmin's VO2max estimate
    cycles:<activity type>   monitoring cumulative cycles (steps for walking/running), reset each local day
"""
import hashlib, json, os, shutil, sqlite3
from collections import Counter
from pathlib import Path

from garmin_fit_sdk import Decoder, Stream

FIT_EPOCH = 631065600  # 1989-12-31T00:00:00Z

SCHEMA = """
create table if not exists files (sha text primary key, path text not null, imported_at integer not null, counts text);
create table if not exists samples (kind text not null, ts integer not null, value real not null, src text not null, primary key (kind, ts)) without rowid;
create index if not exists samples_src on samples (src);
create table if not exists assess (ts integer primary key, data text not null, src text not null);
create table if not exists activities (start integer primary key, data text not null, src text not null);
"""

def connect(path):
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db

def unix(fit_ts):
    return int(fit_ts) + FIT_EPOCH

def decode(path):
    """Messages by type, plus every message in file order as (global number, message)."""
    stream = Stream.from_file(str(path))
    ordered = []
    messages, errors = Decoder(stream).read(convert_datetimes_to_dates=False, convert_types_to_strings=True,
                                            merge_heart_rates=False, expand_sub_fields=True,
                                            mesg_listener=lambda num, m: ordered.append((num, m)))
    if errors and not messages:
        raise ValueError(f"{path}: {errors[0]}")
    messages["_ordered"] = ordered
    return messages

MONITORING = 55

def rows(messages):
    """(samples, assessments, activities) of one decoded file."""
    samples = []
    add = lambda kind, ts, value: value is not None and samples.append((kind, int(ts), float(value)))

    # Monitoring carries 16-bit offsets from the last full timestamp of any message before it in the file
    # (often a monitoring_info), counted in FIT time, whose epoch is not a multiple of 2^16 in Unix time.
    last = None
    for num, m in messages.get("_ordered", []):
        if isinstance(m.get("timestamp"), int):
            last = m["timestamp"]
        elif num == MONITORING and m.get("timestamp_16") is not None and last is not None:
            last += (int(m["timestamp_16"]) - last) & 0xFFFF
        if num != MONITORING or last is None or (m.get("timestamp") is None and m.get("timestamp_16") is None):
            continue
        if m.get("heart_rate"):
            add("hr", unix(last), m["heart_rate"])
        cycles = m.get("steps") if m.get("steps") is not None else m.get("cycles")
        if cycles is not None and m.get("activity_type") is not None:
            add(f"cycles:{m['activity_type']}", unix(last), cycles)
    for m in messages.get("monitoring_hr_data_mesgs", []):
        if m.get("timestamp") is not None and m.get("current_day_resting_heart_rate"):
            add("rhr", unix(m["timestamp"]), m["current_day_resting_heart_rate"])
    for m in messages.get("stress_level_mesgs", []):
        v, t = m.get("stress_level_value"), m.get("stress_level_time")
        if t is not None and v is not None and 0 <= v <= 100:  # negative: off wrist, activity, too much motion
            add("stress", unix(t), v)
    for m in messages.get("respiration_rate_mesgs", []):
        v = m.get("respiration_rate")
        if m.get("timestamp") is not None and v is not None and 0 < v < 60:
            add("resp", unix(m["timestamp"]), v)
    for m in messages.get("spo2_data_mesgs", []):
        v = m.get("reading_spo2")
        if m.get("timestamp") is not None and v and 50 <= v <= 100:
            add("spo2", unix(m["timestamp"]), v)
    for m in messages.get("sleep_level_mesgs", []):
        level = m.get("sleep_level")
        if isinstance(level, str):
            level = {"unmeasurable": 0, "awake": 1, "light": 2, "deep": 3, "rem": 4}.get(level)
        if m.get("timestamp") is not None and level is not None:
            add("sleep", unix(m["timestamp"]), level)
    for m in messages.get("hrv_status_summary_mesgs", []):
        if m.get("timestamp") is not None and m.get("last_night_average"):
            add("hrv", unix(m["timestamp"]), m["last_night_average"])
    for m in messages.get("max_met_data_mesgs", []):
        if m.get("update_time") is not None and m.get("vo2_max"):
            add("vo2max", unix(m["update_time"]), m["vo2_max"])
    for m in messages.get("record_mesgs", []):
        if m.get("timestamp") is not None and m.get("heart_rate"):
            add("hr", unix(m["timestamp"]), m["heart_rate"])

    assessments = []
    when = [unix(m["timestamp"]) for m in messages.get("sleep_level_mesgs", []) if m.get("timestamp") is not None]
    for m in messages.get("sleep_assessment_mesgs", []):
        # The assessment has no timestamp of its own: it belongs to the night in the same file.
        ts = max(when) if when else None
        if ts is not None:
            assessments.append((ts, json.dumps({k: v for k, v in m.items() if v is not None})))

    activities = []
    for s in messages.get("session_mesgs", []):
        if s.get("start_time") is None:
            continue
        keep = ("sport", "sub_sport", "total_timer_time", "total_elapsed_time", "total_distance", "total_calories",
                "avg_heart_rate", "max_heart_rate", "total_training_effect", "total_anaerobic_training_effect",
                "total_ascent")
        data = {k: s[k] for k in keep if s.get(k) is not None}
        activities.append((unix(s["start_time"]), json.dumps(data)))
    return samples, assessments, activities

def store(db, src, samples, assessments, activities):
    """A file's rows in place of what an earlier version of the same file (`src`) gave."""
    for table in ("samples", "assess", "activities"):
        db.execute(f"delete from {table} where src = ?", (src,))
    db.executemany("insert or replace into samples values (?, ?, ?, ?)", [(*r, src) for r in samples])
    db.executemany("insert or replace into assess values (?, ?, ?)", [(*r, src) for r in assessments])
    db.executemany("insert or replace into activities values (?, ?, ?)", [(*r, src) for r in activities])

def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def keep_copy(src, archive, rel):
    """Copy one file from the watch into the archive. Returns (sha, kept path); a new version of a name the
    archive already has goes beside it, so nothing the watch once had is overwritten."""
    archive = Path(archive)
    tmp = archive / ".incoming"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, tmp)
    digest = sha(tmp)
    dest = archive / rel
    if dest.exists() and sha(dest) != digest:
        dest = dest.with_name(f"{dest.stem}.{digest[:8]}{dest.suffix}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        tmp.unlink()
    else:
        os.replace(tmp, dest)
    return digest, dest

def import_files(db, items):
    """Decode every file not imported yet; items are (path, src), src naming the file on the watch, so a newer
    version of it (today's monitoring grows) replaces the older one. Returns {path: message counts} of the new ones."""
    new = {}
    for path, src in items:
        digest = sha(path)
        if db.execute("select 1 from files where sha = ?", (digest,)).fetchone():
            continue
        try:
            messages = decode(path)
        except Exception as e:  # a half-written file of today: the next import reads it whole
            new[str(path)] = {"error": str(e)[:200]}
            continue
        store(db, src, *rows(messages))
        counts = Counter({k: len(v) for k, v in messages.items() if k != "_ordered"})
        db.execute("insert into files values (?, ?, strftime('%s','now'), ?)", (digest, str(path), json.dumps(counts)))
        new[str(path)] = dict(counts)
    db.commit()
    return new
