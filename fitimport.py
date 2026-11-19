"""Garmin FIT files -> rows in wristlogic.db.

Every file the watch had is kept under fit/ (the watch deletes sleep and monitoring files after a Garmin
Connect sync and when its memory fills), and its messages become time series in `samples`, each under the device
that wrote it (the serial number in the file, `devices`), so a second watch or a ring never overwrites the first:

    hr        heart rate, bpm (all-day monitoring and activity records)
    sleep     sleep level: 0 unmeasurable, 1 awake, 2 light, 3 deep, 4 REM (Garmin's own staging)
    sleep_window  1 where the watch's sleep window starts, 0 where it stops
    stress    Garmin stress 0-100 (derived by the watch from HRV)
    resp      respiration rate, breaths/min
    spo2      pulse oximetry, %
    hrv       overnight HRV (ms), when the watch reports it
    hrv5      HRV of each 5 minutes asleep (ms), as the watch reports it
    battery   battery charge, % (the Instinct 2 writes it only during activities)
    rhr       Garmin's resting heart rate of the day
    vo2max    Garmin's VO2max estimate
    cycles:<activity type>   monitoring cumulative cycles (steps for walking/running), reset each local day

`coverage` holds how dense each signal is per device and local day: the median step between samples and the share
of the day they cover.
"""
import hashlib, json, os, re, shutil, sqlite3, statistics
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from garmin_fit_sdk import Decoder, Stream

FIT_EPOCH = 631065600  # 1989-12-31T00:00:00Z

VERSION = 2  # 2: samples per device, devices, coverage
SCHEMA = """
create table if not exists files (sha text primary key, path text not null, imported_at integer not null, counts text);
create table if not exists devices (serial text primary key, manufacturer text, model text, software real,
  first_seen integer, last_seen integer);
create table if not exists samples (device text not null, kind text not null, ts integer not null, value real not null,
  src text not null, primary key (device, kind, ts)) without rowid;
create index if not exists samples_kind on samples (kind, ts);
create index if not exists samples_src on samples (src);
create table if not exists assess (ts integer primary key, data text not null, src text not null, device text);
create table if not exists activities (start integer primary key, data text not null, src text not null, device text);
create table if not exists coverage (device text not null, kind text not null, day text not null, n integer not null,
  period integer not null, covered real not null, primary key (device, kind, day)) without rowid;
"""

def connect(path):
    """The database at `path`. One of an older schema is moved aside as <name>.v<old version>.db and a new one made:
    `rebuild` then fills it again from the archive of FIT files. Returns (db, the old file or None)."""
    path, old = Path(path), None
    if path.exists():
        probe = sqlite3.connect(path)
        version = probe.execute("pragma user_version").fetchone()[0]
        tables = {r[0] for r in probe.execute("select name from sqlite_master where type = 'table'")}
        probe.close()
        if version < VERSION and tables:
            old = path.with_name(f"{path.stem}.v{version or 1}{path.suffix}")
            os.replace(path, old)
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    db.execute(f"pragma user_version = {VERSION}")
    return db, old

def archived(archive):
    """(path, src) of every file in the archive (fit/<watch>/...), oldest copy first, so a newer version of a file
    replaces the older one again; src is the file's name on the watch, as the import from the watch gave it."""
    archive = Path(archive)
    items = []
    for p in archive.glob("*/**/*"):
        if p.is_file() and p.suffix.lower() == ".fit":
            rel = p.relative_to(archive)
            name = re.sub(r"\.[0-9a-f]{8}(\.fit)$", r"\1", rel.name, flags=re.I)  # keep_copy's name for a newer version
            items.append((p.stat().st_mtime, str(p), (p, str(rel.with_name(name)))))
    return [item for _, _, item in sorted(items)]

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

def device(messages):
    """The device that wrote the file: serial, manufacturer, model, software version, time of the file."""
    fid = (messages.get("file_id_mesgs") or [{}])[0]
    creator = next((m for m in messages.get("device_info_mesgs", [])
                    if m.get("device_index") in (None, "creator", 0) and m.get("serial_number") is not None), {})
    serial = fid.get("serial_number") or creator.get("serial_number")
    model = fid.get("garmin_product") or creator.get("garmin_product") or fid.get("product")
    when = fid.get("time_created")
    return {"serial": str(serial) if serial else "unknown", "manufacturer": fid.get("manufacturer"),
            "model": None if model is None else str(model), "software": creator.get("software_version"),
            "when": unix(when) if isinstance(when, int) else None}

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
            # Signed: a record may be a little older than the event logged before it (Instinct 2).
            delta = (int(m["timestamp_16"]) - last) & 0xFFFF
            last += delta - 0x10000 if delta >= 0x8000 else delta
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
    for m in messages.get("event_mesgs", []):
        # Event 74 marks where the watch's sleep window starts and stops.
        if m.get("event") in (74, "sleep") and m.get("timestamp") is not None and m.get("event_type") in ("start", "stop"):
            add("sleep_window", unix(m["timestamp"]), 1 if m["event_type"] == "start" else 0)
    for m in messages.get("hrv_value_mesgs", []):
        if m.get("timestamp") is not None and m.get("value"):
            add("hrv5", unix(m["timestamp"]), m["value"])
    for m in messages.get("battery_mesgs", []):
        if m.get("timestamp") is not None and m.get("capacity") is not None and 0 <= m["capacity"] <= 100:
            add("battery", unix(m["timestamp"]), m["capacity"])
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

def store(db, src, dev, samples, assessments, activities):
    """A file's rows in place of what an earlier version of the same file (`src`) gave."""
    for table in ("samples", "assess", "activities"):
        db.execute(f"delete from {table} where src = ?", (src,))
    serial = dev["serial"]
    db.executemany("insert or replace into samples values (?, ?, ?, ?, ?)", [(serial, *r, src) for r in samples])
    db.executemany("insert or replace into assess values (?, ?, ?, ?)", [(*r, src, serial) for r in assessments])
    db.executemany("insert or replace into activities values (?, ?, ?, ?)", [(*r, src, serial) for r in activities])
    when = dev["when"]
    if serial == "unknown": return  # a file that names no device (some settings files)
    db.execute("""insert into devices values (?, ?, ?, ?, ?, ?) on conflict (serial) do update set
                  manufacturer = coalesce(excluded.manufacturer, manufacturer), model = coalesce(excluded.model, model),
                  software = case when excluded.last_seen >= coalesce(last_seen, 0) then coalesce(excluded.software, software) else software end,
                  first_seen = min(coalesce(first_seen, excluded.first_seen), coalesce(excluded.first_seen, first_seen)),
                  last_seen = max(coalesce(last_seen, excluded.last_seen), coalesce(excluded.last_seen, last_seen))""",
               (serial, dev["manufacturer"], dev["model"], dev["software"], when, when))

TZ = ZoneInfo("Europe/Bratislava")
DENSE = ("hr", "stress", "resp", "spo2", "hrv5", "battery")  # and cycles:*: signals measured over time, not daily values
STAND = 300  # a sample covers the time until the next one, at most this long or two of its usual steps

def coverage(db):
    """Fills `coverage` again: per device, signal and local day, the samples, their median step and the share of
    the day they cover."""
    db.execute("delete from coverage")
    kinds = [k for (k,) in db.execute("select distinct kind from samples")
             if k in DENSE or k.startswith("cycles:")]
    out = []
    for dev, kind in db.execute(f"select distinct device, kind from samples where kind in ({','.join('?' * len(kinds))})",
                                kinds).fetchall():
        days = {}
        for (ts,) in db.execute("select ts from samples where device = ? and kind = ? order by ts", (dev, kind)):
            days.setdefault(datetime.fromtimestamp(ts, TZ).date().isoformat(), []).append(ts)
        for day, ts in days.items():
            steps = [b - a for a, b in zip(ts, ts[1:])]
            period = int(statistics.median(steps)) if steps else 0
            stand = max(STAND, 2 * period)
            covered = sum(min(s, stand) for s in steps) + min(stand, 60)
            out.append((dev, kind, day, len(ts), period, round(min(1.0, covered / 86400), 3)))
    db.executemany("insert into coverage values (?, ?, ?, ?, ?, ?)", out)

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
        store(db, src, device(messages), *rows(messages))
        counts = Counter({k: len(v) for k, v in messages.items() if k != "_ordered"})
        db.execute("insert into files values (?, ?, strftime('%s','now'), ?)", (digest, str(path), json.dumps(counts)))
        new[str(path)] = dict(counts)
    if new:
        coverage(db)
    db.commit()
    return new
